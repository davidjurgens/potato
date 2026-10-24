"""
The pinned list of fetchable bundles (see :mod:`potato.vendoring`).

One entry per library and version. A version bump changes the directory
name, so two Potato versions can share a vendor directory without
overwriting each other's files.
"""

from potato.vendoring import Bundle, BundleFile, register  # noqa: F401


# Mol* (molstar), the structure viewer behind `protein_structure` with
# `engine: molstar`. Only the prebuilt viewer is fetched: one UMD script that
# defines window.molstar, its stylesheet and the licence. Individual files
# rather than the npm tarball, which is ~80 MB unpacked and would also bring
# 19 MB of source maps. The SHA-256 of each file equals the copy inside the
# registry tarball (integrity sha512-KBwdn8ie42a6kqgp/zhCjBb8fIJdBcBq/AMc17iW
# dYLtGF4doxmaMe5Rf0cUUwMj7FiH+/1Hp7F2Px6ywQV/rg==), checked when this entry
# was written. The default engine, 3Dmol.js, is small enough to commit.
_MOLSTAR = "https://cdn.jsdelivr.net/npm/molstar@5.12.0/"
register(Bundle(
    name="molstar",
    version="5.12.0",
    license="MIT",
    homepage="https://molstar.org",
    description="Mol* structure viewer (protein_structure display, engine: molstar)",
    files=(
        BundleFile(_MOLSTAR + "build/viewer/molstar.js", "molstar.js",
                   "8b77dcb87d0920edf5e838a865a9b7f346b177875b1ff85f8689c2e6cfc7cfbd"),
        BundleFile(_MOLSTAR + "build/viewer/molstar.css", "molstar.css",
                   "5b68ceb6d3642549b4e9b2c071e58e41b98a5350ae269180587b39da86925d55"),
        BundleFile(_MOLSTAR + "LICENSE", "LICENSE",
                   "aa42900c6ea7bfcf22d25a4c369025e01a526c66501fd9193f9a8aecee7a0753"),
    ),
    approx_mb=5.3,
))
