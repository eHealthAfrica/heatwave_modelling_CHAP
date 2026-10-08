"""Evaluation harness for the forecasting milestone.

The harness scores stored predictions only. It never imports baselines or
models, never fits anything, and never calls a predictor: it reads prediction
files and labels, and turns them into metrics, confidence intervals and
reports.
"""
