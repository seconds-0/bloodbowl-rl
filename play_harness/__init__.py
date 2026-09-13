"""Human-vs-policy play harness for the BB2025 engine (backend spike).

Modules:
  engine   ctypes wrapper over play_harness/native/bbplay.c (the env TU)
  policy   CPU torch MinGRU policy, checkpoint loading, exact joint sampling
  session  one match: external human seat + policy worker seat, JSON API
  drivers  scripted "human" drivers used to prove the human API end to end
"""
