# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 11:57:09 2025

@author: alere
"""

# File: plugins/screen_A/prompts.py
# Batch 4 — Prompt templates (reserved for future LLM integration)

FT_DECISION_PROMPT = """
You are screening scientific papers against inclusion/exclusion criteria.
Criterion: {criterion_json}
Use ONLY the provided evidence chunks (with page spans) to decide if the paper meets this criterion.
Return JSON with: decision in ["meet","not_meet","uncertain"], confidence in [0,1], and cite which chunks support your call.
"""
