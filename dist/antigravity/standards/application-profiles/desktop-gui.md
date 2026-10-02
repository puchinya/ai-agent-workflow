# Desktop GUI application profile

## Purpose

Use for an explicitly declared desktop graphical application. This profile is not inferred from a GUI toolkit.

## Design questions

Record supported operating systems, windowing/input behavior, accessibility, packaging/update channels, crash reporting, and offline expectations. Add only the platforms and tools this application actually supports.

## Verification

Separate unit, UI automation, packaging, and manual interaction evidence. A platform with no available runner is unverified; a skipped target never passes.
