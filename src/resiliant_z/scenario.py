"""Predeclared operating-envelope thresholds for the controlled scenario.

These are midpoints between configured factorial levels, not thresholds discovered
from data and not real-world warehouse specifications.
"""

HIGH_DEMAND_THRESHOLD = 0.80  # midpoint of 0.55 and 1.05
HIGH_PRIORITY_THRESHOLD = 0.325  # midpoint of 0.15 and 0.50
JUNCTION_PRESSURE_TRIGGER = 2  # one in service plus at least one queued task
