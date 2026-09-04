Fixture: a target repo that owns its virtualenv. Tests copy it to a temp dir and create `.venv/` there with
`python3 -m venv --without-pip`, so `testcmd.detect()` must find *that* interpreter, never Rehorse's own.
