from flask import Flask, render_template, request, redirect, send_file, flash
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import base64
from sqlalchemy import and_
from flask import render_template, request, redirect, url_for, flash
from . import subsys_bp, db
from .models import InterruptionRequest

@measurments_bp.route('/')
def home():
    return render_template('index.html')
# Application Routes
@app.route('/', methods=['GET', 'POST'])
def index():
    records = MeasurementRecord.query.order_by(MeasurementRecord.timestamp.desc()).all()
    error = None

    if request.method == 'POST' and 'submit_measurement' in request.form:
        try:
            required_fields = {
                'substation_name': 'Substation Name',
                'bay_name': 'Bay Name',
                'voltage_level': 'Voltage Level',
                'relay_type': 'Relay Type',
                'ct_ratio': 'CT Ratio',
                'vt_ratio': 'VT Ratio'
            }

            missing = [name for field, name in required_fields.items() if not request.form.get(field)]
            if missing:
                raise ValueError(f"Missing required fields: {', '.join(missing)}")

            record = MeasurementRecord(
                substation_name=request.form['substation_name'],
                bay_name=request.form['bay_name'],
                voltage_level=request.form['voltage_level'],
                relay_type=request.form['relay_type'],
                ct_ratio=request.form['ct_ratio'],
                vt_ratio=request.form['vt_ratio']
            )
            db.session.add(record)
            db.session.commit()
            process_measurements(record.id, request.form)
            flash('Measurement recorded successfully!', 'success')
            return redirect('/')

        except Exception as e:
            db.session.rollback()
            error = str(e)
            flash(f'Error: {error}', 'danger')

    return render_template('index.html', records=records, error=error)

@app.route('/export', methods=['POST'])
def export_data():
    try:
        record_ids = request.form.getlist('record_ids')
        if not record_ids:
            flash('No records selected for export', 'warning')
            return redirect('/')

        records = MeasurementRecord.query.filter(MeasurementRecord.id.in_(record_ids)).all()
        output = BytesIO()

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # Summary Sheet
            summary_data = [{
                'ID': r.id,
                'Timestamp': r.timestamp.strftime('%Y-%m-%d %H:%M'),
                'Substation': r.substation_name,
                'Bay': r.bay_name,
                'Voltage Level': r.voltage_level,
                'Relay Type': r.relay_type
            } for r in records]
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)

            # Detailed Sheets
            for record in records:
                sheet_name = f"{record.bay_name}_{record.id}"
                start_row = 0

                # Currents
                currents = [[c.phase, c.value, c.angle] for c in record.phase_currents]
                currents_df = pd.DataFrame(currents, columns=['Phase', 'Value (A)', 'Angle'])
                currents_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
                start_row += len(currents_df) + 3

                # Voltages
                voltages = [[v.phase, v.value, v.angle] for v in record.phase_voltages]
                voltages_df = pd.DataFrame(voltages, columns=['Phase', 'Value (kV)', 'Angle'])
                voltages_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
                start_row += len(voltages_df) + 3

                # Sequences
                sequences = [[s.component, s.value] for s in record.sequence_components]
                sequences_df = pd.DataFrame(sequences, columns=['Component', 'Value'])
                sequences_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)

        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            download_name=f"{record.substation_name}_substation_data_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            as_attachment=True
        )

    except Exception as e:
        flash(f'Export failed: {str(e)}', 'danger')
        return redirect('/')

# Report Routes
@app.route('/reports')
def reports_dashboard():
    return render_template('reports_dashboard.html')

@app.route('/reports/summary', methods=['GET', 'POST'])
def summary_report():
    substations = get_unique_values(MeasurementRecord.substation_name)
    bays = get_unique_values(MeasurementRecord.bay_name)

    if request.method == 'POST':
        filter_data = get_report_filters(request.form)
        records = get_filtered_records(filter_data)
        report_data = {
            'currents': generate_phase_report(records, 'current'),
            'voltages': generate_phase_report(records, 'voltage'),
            'sequence_components': generate_sequence_report(records),
            'summary_stats': generate_summary_statistics(records)
        }
        return render_template('summary_report.html',
                            report_data=report_data,
                            filters=filter_data,
                            substations=substations,
                            bays=bays)

    return render_template('summary_report_form.html',
                         substations=substations,
                         bays=bays)
@app.route('/reports/thresholds', methods=['GET', 'POST'])
def threshold_report():
    thresholds = {'current': 1600, 'voltage': 500, 'I0': 50, 'V0': 50}
    substations = get_unique_values(MeasurementRecord.substation_name)
    bays = get_unique_values(MeasurementRecord.bay_name)

    if request.method == 'POST':
        filter_data = get_report_filters(request.form)
        records = get_filtered_records(filter_data)
        alerts = check_thresholds(records, thresholds)
        return render_template('threshold_report.html',
                             alerts=alerts,
                             thresholds=thresholds,
                             filters=filter_data,
                             substations=substations,
                             bays=bays)

    return render_template('threshold_report_form.html',
                         substations=substations,
                         bays=bays,
                         thresholds=thresholds)

@app.route('/reports/trends', methods=['GET', 'POST'])
def trend_analysis():
    parameters = ['IA', 'IB', 'IC', 'VA', 'VB', 'VC',
                 'I0', 'I1', 'I2', 'V0', 'V1', 'V2']

    if request.method == 'POST':
        filter_data = get_report_filters(request.form)
        selected_params = request.form.getlist('parameters')
        plot_data = generate_trend_plot(filter_data, selected_params)
        return render_template('trend_analysis.html',
                             plot_data=plot_data,
                             parameters=selected_params,
                             filters=filter_data,
                             substations=get_unique_values(MeasurementRecord.substation_name),
                             bays=get_unique_values(MeasurementRecord.bay_name))

    return render_template('trend_analysis_form.html',
                         parameters=parameters,
                         substations=get_unique_values(MeasurementRecord.substation_name),
                         bays=get_unique_values(MeasurementRecord.bay_name))

# Helper Functions
def process_measurements(record_id, form_data):
    try:
        # Phase Currents
        for phase in ['IA', 'IB', 'IC', 'IN']:
            db.session.add(PhaseCurrent(
                record_id=record_id,
                phase=phase,
                value=float(form_data[f'{phase}_value']),
                angle=float(form_data[f'{phase}_angle'])
            ))

        # Phase Voltages
        for phase in ['VA', 'VB', 'VC', 'VN']:
            db.session.add(PhaseVoltage(
                record_id=record_id,
                phase=phase,
                value=float(form_data[f'{phase}_value']),
                angle=float(form_data[f'{phase}_angle'])
            ))

        # Sequence Components
        for comp in ['I0', 'I1', 'I2', 'V0', 'V1', 'V2']:
            db.session.add(SequenceComponent(
                record_id=record_id,
                component=comp,
                value=float(form_data[f'{comp}_value'])
            ))

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise ValueError(f"Invalid numeric value: {str(e)}")

def get_unique_values(column):
    return [v[0] for v in db.session.query(column).distinct().all()]

def get_report_filters(form_data):
    return {
        'start_date': form_data.get('start_date'),
        'end_date': form_data.get('end_date'),
        'substation': form_data.get('substation'),
        'bay': form_data.get('bay')
    }

def get_filtered_records(filters):
    query = MeasurementRecord.query

    if filters['start_date']:
        start = datetime.strptime(filters['start_date'], '%Y-%m-%d')
        query = query.filter(MeasurementRecord.timestamp >= start)
    if filters['end_date']:
        end = datetime.strptime(filters['end_date'], '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(MeasurementRecord.timestamp < end)
    if filters['substation']:
        query = query.filter_by(substation_name=filters['substation'])
    if filters['bay']:
        query = query.filter_by(bay_name=filters['bay'])

    return query.order_by(MeasurementRecord.timestamp).all()

def generate_phase_report(records, measurement_type):
    data = []
    for record in records:
        measurements = record.phase_currents if measurement_type == 'current' else record.phase_voltages
        for m in measurements:
            data.append({
                'substation': record.substation_name,
                'bay': record.bay_name,
                'phase': m.phase,
                'value': m.value,
                'angle': m.angle
            })

    df = pd.DataFrame(data)
    return df.groupby(['substation', 'bay', 'phase']).agg({
        'value': ['min', 'max', 'mean', 'std'],
        'angle': ['mean']
    }).round(2) if not df.empty else pd.DataFrame()

def generate_sequence_report(records):
    data = []
    for record in records:
        for sc in record.sequence_components:
            data.append({
                'substation': record.substation_name,
                'bay': record.bay_name,
                'component': sc.component,
                'value': sc.value
            })

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    return df.groupby(['substation', 'bay', 'component']).agg({
        'value': ['min', 'max', 'mean', 'std']
    }).round(2) #if not df.empty else pd.DataFrame()

def check_thresholds(records, thresholds):
    alerts = []
    for record in records:
        for pc in record.phase_currents:
            if pc.value > thresholds['current']:
                alerts.append({
                    'timestamp': record.timestamp,
                    'type': 'Current',
                    'phase': pc.phase,
                    'value': pc.value,
                    'threshold': thresholds['current'],
                    'substation': record.substation_name,
                    'bay': record.bay_name
                })

        for sc in record.sequence_components:
            if sc.component in thresholds and sc.value > thresholds[sc.component]:
                alerts.append({
                    'timestamp': record.timestamp,
                    'type': 'Sequence',
                    'component': sc.component,
                    'value': sc.value,
                    'threshold': thresholds[sc.component],
                    'substation': record.substation_name,
                    'bay': record.bay_name
                })

    return pd.DataFrame(alerts)

def generate_trend_plot(filter_data, parameters):
    records = get_filtered_records(filter_data)
    if not records or not parameters:
        return None

    plt.figure(figsize=(14, 8))
    plt.style.use('ggplot')
    colormap = plt.cm.get_cmap('tab20', len(parameters))

    legend_handles = []

    for idx, param in enumerate(parameters):
        timestamps = []
        values = []

        for record in records:
            measurements = []
            if param in ['I0', 'I1', 'I2', 'V0', 'V1', 'V2']:
                measurements = [sc for sc in record.sequence_components if sc.component == param]
            elif param.startswith('I'):
                measurements = [pc for pc in record.phase_currents if pc.phase == param]
            elif param.startswith('V'):
                measurements = [pv for pv in record.phase_voltages if pv.phase == param]

            for m in measurements:
                timestamps.append(record.timestamp)
                values.append(m.value)

        if timestamps:
            line, = plt.plot(timestamps, values,
                           marker='o',
                           linestyle='-',
                           color=colormap(idx),
                           label=param)
            legend_handles.append(line)

    if not legend_handles:
        return None

    plt.title(f'Trend Analysis: {", ".join(parameters)}')
    plt.xlabel('Timestamp')
    plt.ylabel('Value')
    plt.legend(handles=legend_handles, bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plot_url = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close()

    return plot_url

def generate_summary_statistics(records):
    stats = {
        'total_records': len(records),
        'substations': len({r.substation_name for r in records}),
        'bays': len({r.bay_name for r in records}),
        'time_range': None,
        'current_stats': None,
        'voltage_stats': None
    }

    if records:
        timestamps = [r.timestamp for r in records]
        stats['time_range'] = {
            'start': min(timestamps).strftime('%Y-%m-%d'),
            'end': max(timestamps).strftime('%Y-%m-%d')
        }

        current_values = [pc.value for r in records for pc in r.phase_currents]
        voltage_values = [pv.value for r in records for pv in r.phase_voltages]

        stats['current_stats'] = {
            'max': round(max(current_values), 2) if current_values else 0,
            'min': round(min(current_values), 2) if current_values else 0,
            'avg': round(sum(current_values)/len(current_values), 2) if current_values else 0
        }

        stats['voltage_stats'] = {
            'max': round(max(voltage_values), 2) if voltage_values else 0,
            'min': round(min(voltage_values), 2) if voltage_values else 0,
            'avg': round(sum(voltage_values)/len(voltage_values), 2) if voltage_values else 0
        }

    return stats

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=3000, debug=True)