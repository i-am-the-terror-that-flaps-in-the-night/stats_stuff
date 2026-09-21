# Vendored shared libraries

`libgomp.so.1` — GNU OpenMP runtime (x86_64, glibc), extracted from the
manylinux2014 wheel of scikit-learn 1.6.1 (which bundles it as
`scikit_learn.libs/libgomp-a34b3233.so.1.0.0`). LightGBM's Linux wheel links
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
