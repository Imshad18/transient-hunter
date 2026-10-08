# Transient Hunter

Pulls new supernova candidates from the Zwicky Transient Facility alert stream (via the ALeRCE broker),
fits their light curves and ranks them by how worthwhile follow-up observations would be right now.

![screenshot](shots/main.png)

## Usage

```bash
./run.sh        # Linux / macOS / WSL
run.bat         # Windows
```

Open http://localhost:8003. A scan runs on start-up if the last one is older than 12 hours.

## What it does

1. Queries ALeRCE for alerts whose image cut-outs look like supernovae, first seen in the last 7–30 days.
2. Downloads each light curve (detections and upper limits) and fits a Bazin model per band.
3. Measures age, latest and peak magnitude, recent trend, rise time, decline rate and g − r colour.
4. Gives a light-curve type hint (SN Ia-like, plateau, fast, young and hot, slow riser) next to the
   ALeRCE classifier result.
5. Scores each object for follow-up: brightness, youth, still rising, colour, recent detections.
6. Computes how many dark hours each object is above 30° altitude tonight from your location.

The detail view shows the light curve with fits, ZTF science / reference / difference cut-outs,
an altitude chart for tonight, and links to ALeRCE, Lasair and the Transient Name Server.

## Limitations

- Type hints are based on light-curve shape and colour only; a spectrum is needed to classify.
- No automatic Transient Name Server cross-match (it needs an API key); use the TNS link before reporting anything.
- Observability ignores the Moon and local horizon.
