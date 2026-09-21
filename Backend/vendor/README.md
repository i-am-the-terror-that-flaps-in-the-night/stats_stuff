# Vendored shared libraries

`libgomp.so.1` — GNU OpenMP runtime (x86_64, glibc ≥ 2.17), the file
`/usr/lib/x86_64-linux-gnu/libgomp.so.1.0.0` from Debian bullseye's
`libgomp1_10.2.1-6_amd64.deb`. It must be a copy whose ELF SONAME is
literally `libgomp.so.1`: the copies auditwheel bundles inside manylinux
wheels (scikit-learn, xgboost) are renamed to `libgomp-<hash>.so.1.0.0`
and preloading one of those does NOT satisfy LightGBM's request. LightGBM's Linux wheel links
against it but does not ship it, and Vercel's Python runtime (an AWS
Lambda-style image) does not have it installed, so `import lightgbm` fails
with "libgomp.so.1: cannot open shared object file" and every `/api/predict*`
route returns 500.

`Backend/predictor.py::_import_lightgbm()` tries the plain import first and
only preloads this file (via `ctypes.CDLL(..., RTLD_GLOBAL)`) when that
import raises for a missing libgomp. On macOS, Render and any machine with
gcc's runtime installed, the file is never touched.

Licence: GPL-3.0 with the GCC Runtime Library Exception, same as any
program linked against libgomp.
