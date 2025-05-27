from flask import Flask, render_template, request, redirect, send_file, flash
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import base64
from sqlalchemy import and_
from . import db
from datetime import datetime

# Database Models
class MeasurementRecord(db.Model):
    measurments = 'measurments_requests'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    substation_name = db.Column(db.String(100), nullable=False)
    bay_name = db.Column(db.String(100), nullable=False)
    voltage_level = db.Column(db.String(50), nullable=False)
    relay_type = db.Column(db.String(100), nullable=False)
    ct_ratio = db.Column(db.String(50), nullable=False)
    vt_ratio = db.Column(db.String(50), nullable=False)

    phase_currents = db.relationship('PhaseCurrent', backref='record', cascade='all, delete-orphan')
    phase_voltages = db.relationship('PhaseVoltage', backref='record', cascade='all, delete-orphan')
    sequence_components = db.relationship('SequenceComponent', backref='record', cascade='all, delete-orphan')

class PhaseCurrent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('measurement_record.id'), nullable=False)
    phase = db.Column(db.String(2), nullable=False)
    value = db.Column(db.Float, nullable=False)
    angle = db.Column(db.Float, nullable=False)

class PhaseVoltage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('measurement_record.id'), nullable=False)
    phase = db.Column(db.String(2), nullable=False)
    value = db.Column(db.Float, nullable=False)
    angle = db.Column(db.Float, nullable=False)

class SequenceComponent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('measurement_record.id'), nullable=False)
    component = db.Column(db.String(2), nullable=False)
    value = db.Column(db.Float, nullable=False)