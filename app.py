from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import pandas as pd
from io import BytesIO
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'substation.db'))
db = SQLAlchemy(app)
csrf = CSRFProtect(app)

# Database Models
class MeasurementRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    element_type = db.Column(db.String(20), nullable=False)
    winding_type = db.Column(db.String(20))
    substation_name = db.Column(db.String(100), nullable=False)
    bay_name = db.Column(db.String(100), nullable=False)
    voltage_level = db.Column(db.String(50), nullable=False)
    relay_type = db.Column(db.String(100), nullable=False)
    
    # Transformer Specific Fields
    oil_temp = db.Column(db.Float)
    tap_position = db.Column(db.Integer)
    hv_ia = db.Column(db.Float)
    hv_ib = db.Column(db.Float)
    hv_ic = db.Column(db.Float)
    mv_ia = db.Column(db.Float)
    mv_ib = db.Column(db.Float)
    mv_ic = db.Column(db.Float)
    lv_ia = db.Column(db.Float)
    lv_ib = db.Column(db.Float)
    lv_ic = db.Column(db.Float)
    hv_ct_ratio = db.Column(db.String(50))
    mv_ct_ratio = db.Column(db.String(50))
    lv_ct_ratio = db.Column(db.String(50))
    hv_active_power = db.Column(db.Float)
    hv_reactive_power = db.Column(db.Float)
    mv_active_power = db.Column(db.Float)
    mv_reactive_power = db.Column(db.Float)
    lv_active_power = db.Column(db.Float)
    lv_reactive_power = db.Column(db.Float)
    hv_winding_temp = db.Column(db.Float)
    mv_winding_temp = db.Column(db.Float)
    lv_winding_temp = db.Column(db.Float)

    # Line Specific Fields
    active_power = db.Column(db.Float)
    reactive_power = db.Column(db.Float)
    ct_ratio = db.Column(db.String(50))

    # Line Specific Relationships
    phase_currents = db.relationship('PhaseCurrent', backref='record', cascade='all, delete-orphan')
    phase_voltages = db.relationship('PhaseVoltage', backref='record', cascade='all, delete-orphan')
    sequence_components = db.relationship('SequenceComponent', backref='record', cascade='all, delete-orphan')

class PhaseCurrent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('measurement_record.id'), nullable=False)
    phase = db.Column(db.String(2), nullable=False)
    value = db.Column(db.Float, nullable=False)

class PhaseVoltage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('measurement_record.id'), nullable=False)
    phase = db.Column(db.String(2), nullable=False)
    value = db.Column(db.Float, nullable=False)

class SequenceComponent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('measurement_record.id'), nullable=False)
    component = db.Column(db.String(2), nullable=False)
    value = db.Column(db.Float, nullable=False)

@app.route('/', methods=['GET', 'POST'])
def index():
    records = MeasurementRecord.query.order_by(MeasurementRecord.timestamp.desc()).all()
    
    if request.method == 'POST' and 'submit_measurement' in request.form:
        try:
            # Validate common fields
            required_common_fields = ['element_type', 'substation_name', 'bay_name', 'voltage_level', 'relay_type']
            for field in required_common_fields:
                if not request.form.get(field):
                    raise ValueError(f"Missing required field: {field}")

            record_data = {
                'element_type': request.form['element_type'],
                'substation_name': request.form['substation_name'],
                'bay_name': request.form['bay_name'],
                'voltage_level': request.form['voltage_level'],
                'relay_type': request.form['relay_type']
            }

            if record_data['element_type'] == 'transformer':
                if not request.form.get('winding_type'):
                    raise ValueError("Missing required field: winding_type")
                record_data.update(process_transformer_data(request.form))
            else:
                record_data.update(process_line_data(request.form))

            record = MeasurementRecord(**record_data)
            db.session.add(record)
            db.session.flush()

            if record.element_type == 'line':
                process_phase_measurements(record.id, request.form)

            db.session.commit()
            flash('Measurement saved successfully!', 'success')
            return redirect(url_for('index'))

        except ValueError as ve:
            db.session.rollback()
            flash(f'Validation error: {str(ve)}', 'danger')
            app.logger.error(f"Validation error: {str(ve)}")
        except Exception as e:
            db.session.rollback()
            flash(f'Database error: {str(e)}', 'danger')
            app.logger.error(f"Database error: {str(e)}", exc_info=True)

    return render_template('index.html', records=records)

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
                sheet_name = f"{record.bay_name}_{record.id}"[:31]  # Excel sheet name limit
                start_row = 0

                # Add element-specific data
                if record.element_type == 'transformer':
                    transformer_data = {
                        'Tap Position': [record.tap_position],
                        'Oil Temperature (°C)': [record.oil_temp],
                        'HV Winding Temp (°C)': [record.hv_winding_temp],
                        'MV Winding Temp (°C)': [record.mv_winding_temp],
                        'LV Winding Temp (°C)': [record.lv_winding_temp],
                        'HV Active Power (MW)': [record.hv_active_power],
                        'HV Reactive Power (MVAR)': [record.hv_reactive_power],
                        'MV Active Power (MW)': [record.mv_active_power],
                        'MV Reactive Power (MVAR)': [record.mv_reactive_power],
                        'LV Active Power (MW)': [record.lv_active_power],
                        'LV Reactive Power (MVAR)': [record.lv_reactive_power],
                        'HV CT Ratio': [record.hv_ct_ratio],
                        'MV CT Ratio': [record.mv_ct_ratio],
                        'LV CT Ratio': [record.lv_ct_ratio]
                    }
                    pd.DataFrame(transformer_data).to_excel(
                        writer, sheet_name=sheet_name, startrow=start_row, index=False)
                    start_row += 14

                else:
                    line_data = {
                        'Active Power (MW)': [record.active_power],
                        'Reactive Power (MVAR)': [record.reactive_power],
                        'CT Ratio': [record.ct_ratio]
                    }
                    pd.DataFrame(line_data).to_excel(
                        writer, sheet_name=sheet_name, startrow=start_row, index=False)
                    start_row += 5

                # Currents
                currents = [[c.phase, c.value] for c in record.phase_currents]
                currents_df = pd.DataFrame(currents, columns=['Phase', 'Value (A)'])
                currents_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
                start_row += len(currents_df) + 3

                # Voltages
                voltages = [[v.phase, v.value] for v in record.phase_voltages]
                voltages_df = pd.DataFrame(voltages, columns=['Phase', 'Value (kV)'])
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
            download_name=f"{records[0].substation_name}_substation_data_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
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
    parameters = ['IA', 'IB', 'IC', 'VA', 'VB', 'VC', 'I0', 'I1', 'I2', 'V0', 'V1', 'V2']

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
                'timestamp': record.timestamp,
                'substation': record.substation_name,
                'bay': record.bay_name,
                'phase': m.phase,
                'value': m.value
            })

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    return df.groupby(['substation', 'bay', 'phase']).agg({
        'value': ['min', 'max', 'mean', 'std']
    }).round(2)

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
    }).round(2)

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

        for pv in record.phase_voltages:
            if pv.value > thresholds['voltage']:
                alerts.append({
                    'timestamp': record.timestamp,
                    'type': 'Voltage',
                    'phase': pv.phase,
                    'value': pv.value,
                    'threshold': thresholds['voltage'],
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

def process_transformer_data(form_data):
    try:
        transformer_data = {
            'winding_type': form_data.get('winding_type', 'two'),
            'oil_temp': float(form_data['oil_temp']) if form_data.get('oil_temp') else None,
            'tap_position': int(form_data['tap_position']) if form_data.get('tap_position') else None,
            'hv_ia': float(form_data['hv_ia']) if form_data.get('hv_ia') else None,
            'hv_ib': float(form_data['hv_ib']) if form_data.get('hv_ib') else None,
            'hv_ic': float(form_data['hv_ic']) if form_data.get('hv_ic') else None,
            'mv_ia': float(form_data['mv_ia']) if form_data.get('mv_ia') else None,
            'mv_ib': float(form_data['mv_ib']) if form_data.get('mv_ib') else None,
            'mv_ic': float(form_data['mv_ic']) if form_data.get('mv_ic') else None,
            'hv_ct_ratio': float(form_data['hv_ct_ratio']) if form_data.get('hv_ct_ratio') else None,
            'mv_ct_ratio': float(form_data['mv_ct_ratio']) if form_data.get('mv_ct_ratio') else None,
            'hv_active_power': float(form_data['hv_active_power']) if form_data.get('hv_active_power') else None,
            'hv_reactive_power': float(form_data['hv_reactive_power']) if form_data.get('hv_reactive_power') else None,
            'mv_active_power': float(form_data['mv_active_power']) if form_data.get('mv_active_power') else None,
            'mv_reactive_power': float(form_data['mv_reactive_power']) if form_data.get('mv_reactive_power') else None,
            'hv_winding_temp': float(form_data['hv_winding_temp']) if form_data.get('hv_winding_temp') else None,
            'mv_winding_temp': float(form_data['mv_winding_temp']) if form_data.get('mv_winding_temp') else None,
            'ct_ratio': None
        }

        if transformer_data['winding_type'] == 'three':
            transformer_data.update({
                'lv_ia': float(form_data.get('lv_ia', 0)),
                'lv_ib': float(form_data.get('lv_ib', 0)),
                'lv_ic': float(form_data.get('lv_ic', 0)),
                'lv_ct_ratio': float(form_data.get('lv_ct_ratio', 0)),
                'lv_active_power': float(form_data.get('lv_active_power', 0)),
                'lv_reactive_power': float(form_data.get('lv_reactive_power', 0)),
                'lv_winding_temp': float(form_data.get('lv_winding_temp', 0))
            })
        else:
            transformer_data.update({
                'lv_ia': None,
                'lv_ib': None,
                'lv_ic': None,
                'lv_ct_ratio': None,
                'lv_active_power': None,
                'lv_reactive_power': None,
                'lv_winding_temp': None
            })

        # Validate required transformer fields
        required_fields = ['oil_temp', 'tap_position', 'hv_winding_temp', 'mv_winding_temp',
                          'hv_active_power', 'hv_reactive_power', 'mv_active_power', 'mv_reactive_power',
                          'hv_ia', 'hv_ib', 'hv_ic', 'mv_ia', 'mv_ib', 'mv_ic',
                          'hv_ct_ratio', 'mv_ct_ratio']
        for field in required_fields:
            if transformer_data.get(field) is None:
                raise ValueError(f"Missing required transformer field: {field}")

        return transformer_data

    except ValueError as ve:
        raise ValueError(f"Transformer data error: {str(ve)}")
    except Exception as e:
        raise ValueError(f"Error processing transformer data: {str(e)}")

def process_line_data(form_data):
    try:
        line_data = {
            'winding_type': None,
            'oil_temp': None,
            'tap_position': None,
            'hv_ia': None, 'hv_ib': None, 'hv_ic': None,
            'mv_ia': None, 'mv_ib': None, 'mv_ic': None,
            'lv_ia': None, 'lv_ib': None, 'lv_ic': None,
            'hv_ct_ratio': None, 'mv_ct_ratio': None, 'lv_ct_ratio': None,
            'hv_active_power': None, 'hv_reactive_power': None,
            'mv_active_power': None, 'mv_reactive_power': None,
            'lv_active_power': None, 'lv_reactive_power': None,
            'hv_winding_temp': None, 'mv_winding_temp': None, 'lv_winding_temp': None,
            'active_power': float(form_data['active_power']) if form_data.get('active_power') else None,
            'reactive_power': float(form_data['reactive_power']) if form_data.get('reactive_power') else None,
            'ct_ratio': float(form_data['ct_ratio']) if form_data.get('ct_ratio') else None
        }

        # Validate required fields
        required_fields = ['active_power', 'reactive_power', 'ct_ratio']
        for field in required_fields:
            if line_data.get(field) is None:
                raise ValueError(f"Missing required field: {field}")

        return line_data

    except ValueError as ve:
        raise ValueError(f"Line data error: {str(ve)}")
    except Exception as e:
        raise ValueError(f"Error processing line data: {str(e)}")

def process_phase_measurements(record_id, form_data):
    try:
        # Validate line-specific fields
        for phase in ['IA', 'IB', 'IC', 'IN']:
            if not form_data.get(f'{phase}_value'):
                raise ValueError(f"Missing required field for phase current: {phase}")
        for phase in ['VA', 'VB', 'VC', 'VN']:
            if not form_data.get(f'{phase}_value'):
                raise ValueError(f"Missing required field for phase voltage: {phase}")
        for comp in ['I0', 'I1', 'I2', 'V0', 'V1', 'V2']:
            if not form_data.get(f'{comp}_value'):
                raise ValueError(f"Missing required field for sequence component: {comp}")

        # Phase Currents
        for phase in ['IA', 'IB', 'IC', 'IN']:
            db.session.add(PhaseCurrent(
                record_id=record_id,
                phase=phase,
                value=float(form_data[f'{phase}_value'])
            ))

        # Phase Voltages
        for phase in ['VA', 'VB', 'VC', 'VN']:
            db.session.add(PhaseVoltage(
                record_id=record_id,
                phase=phase,
                value=float(form_data[f'{phase}_value'])
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
        raise ValueError(f"Phase measurement error: {str(e)}")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))
