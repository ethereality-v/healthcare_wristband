"""Laptop app for the ECE 198 healthcare wristband.

Reads the band (USB serial, Wi-Fi UDP, or a built-in simulator), runs prescribed exercise
sessions, checks heart rate / SpO2 safety, logs everything to a JSON database and serves a
local dashboard. The computer-vision coach posts its results to ``POST /api/cv``.
"""

__version__ = "1.0.0"
