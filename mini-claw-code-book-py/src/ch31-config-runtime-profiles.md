# Chapter 31: Config Files and Runtime Profiles (coming soon)

The harness now has enough runtime surface that Python defaults are no longer
enough.

This chapter will define:

- local config files for harness defaults
- environment overrides
- runtime profile selection
- how config and control policy should stay separate

The code should stay flat and readable.

The goal is not a giant config framework.

The goal is a small, explicit loader that makes the harness easier to run and
teach.
