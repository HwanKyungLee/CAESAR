# Literature cross sections — sources (not redistributed in the public release)

The three files in this folder are the original high-resolution cross sections that Augur convolves with the
instrument line shape (`calibration/build_cold_refs.py`). No explicit open licence for redistribution was found for
any of them (checked 2026-09-27), so the public archive leaves them out. Download them from the providers and put
them here under the same file names.

| File | Reference | DOI |
|---|---|---|
| `NO2_Vandaele(2002)_294K_384-725nm(vis-dilut5).txt` | Vandaele, A. C. et al.: High-resolution Fourier transform measurement of the NO2 visible and near-infrared absorption cross sections: Temperature and pressure effects, J. Geophys. Res., 107, 2002. Data: BIRA-IASB spectroscopy group (spectrolab.aeronomie.be) | 10.1029/2001JD000971 |
| `CHOCHO_Volkamer(2005)_296K_250.031-526.168nm(0.001nm).txt` | Volkamer, R. et al.: High-resolution absorption cross-section of glyoxal in the UV–vis and IR spectral ranges, J. Photochem. Photobiol. A, 172, 2005 | 10.1016/j.jphotochem.2004.11.011 |
| `O4_ThalmanVolkamer(2013)_293K_335.749-600.802nm.txt` | Thalman, R. and Volkamer, R.: Temperature dependent absorption cross-sections of O2–O2 collision pairs between 340 and 630 nm and at atmospherically relevant pressure, Phys. Chem. Chem. Phys., 15, 2013 | 10.1039/c3cp50968k |

H2O is computed from HITRAN line data (cite the HITRAN edition used, following the HITRAN citation policy).
Most of these files are also collected in the MPI-Mainz UV/VIS Spectral Atlas (Keller-Rudek et al., 2013,
doi:10.5194/essd-5-365-2013).

The instrument-convolved references in `reference_data/wv_cal/*/Ref_*_Dynamic-ILS-Applied.dat` are derived
products and ship with the code; cite the original papers above when using them.
