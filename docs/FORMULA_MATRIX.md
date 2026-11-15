# Formula and edition matrix

Three calculation modes exist and are never mixed inside one calculation.

| Mode (`mode`) | Meaning | Used for |
|---|---|---|
| `iso2024` | ISO 9613-2:2024, published equations as read from the supplied scan | default for all predictions |
| `draft2026` | ISO 9613-2:2024 with the **DRAFT** DAmd 1 replacements of eqs. (18) and (21). Not an official amendment | experimental comparison |
| `iso1996` | ISO 9613-2:1996 compatibility, reproduced as needed by ISO/TR 17534-3 | benchmark comparison only |

Page numbers: `PDF p.` is the page of `standard_iso_9613-2_2024.pdf` (printed page + 8).

## Terms

| Term | 2024 equation | Source read | MATLAB | Notes |
|---|---|---|---|---|
| Level at receiver | (3) `L = L_W + D_c - A` | PDF p. 15 | `run_acoustic_case` | `L_W` is sound **power** (dB re 1 pW), never an SPL at 1 m |
| Total attenuation | (5) `A = A_div + A_atm + A_gr + A_bar + A_misc` | PDF p. 16 | `run_acoustic_case` | `A_misc` not modelled (reported as 0 and listed) |
| Broadband / A-weighted | (6) energy sum over the eight bands | PDF p. 16 | `nb_energy_sum` | never an average of dB |
| Long-term level | (7) `L(LT) = L(DW) - C_met` | PDF p. 16 | `nb_cmet` | not applied unless `C0` is given |
| Divergence | (8) `A_div = 20 lg(d/d0) + 11` | PDF p. 16 | `nb_adiv` | true 3D distance |
| Atmosphere | (9) `A_atm = alpha d / 1000` | PDF p. 17 | `nb_aatm` | ISO 9613-1:1993 (3)-(5); **exact** base-10 centre frequencies (6) required by 7.2 |
| Ground regions | (10) `G = sum(G_n d_n) / sum(d_n)` | PDF p. 18 | `nb_ground_factors` | source/receiver regions `30 h`, heights above **local** ground |
| Ground attenuation | (11) `A_gr = -10 lg[1 + (10^(-A'/10) - 1) K_geo]`, (12) `A' = A_S + A_R + A_m`, (13) `K_geo` | PDF p. 18 | `nb_agr` | may be negative, never clamped |
| Ground terms | Table 3, `a'`..`d'`, `q` | PDF p. 19 | `nb_agr` | |
| Simplified ground | (14) `A_gr = 4.8 - (2 h_m/d)(17 + 300/d) >= 0`, (15) `D_Omega = 10 lg(1 + K_geo)` | PDF pp. 20-21 | `nb_agr_simplified` | A-weighted levels only |
| Barrier, top | (16) `A_bar = D_z - A_gr` if `A_gr > 0`, (17) `A_bar = D_z` otherwise | PDF p. 22 | `nb_abar` | |
| Diffraction `D_z` | (18) `10 lg[1 + (2 + (C2/lambda) C3 z) K_met]`, `z > z_min`, else 0; (19) `z_min = -2 lambda/(C2 C3)`; (20) `C3` | PDF p. 24 | `nb_dz` | `C2 = 20`; `lambda = 340/f` at the **nominal** frequency |
| `K_met` | (21) `exp{-(1/2000) sqrt([max(dss,dsr)+e] min(dss,dsr) d / [2(z - z_min)])}` | PDF p. 24 | `nb_dz` | lateral paths: `K_met = 1` |
| Path difference | (22) `z = dss + dsr + e - d`; (23) `z = max(z_n)`; (24) alternative | PDF pp. 25-26 | `nb_geom2d` | negative sign when the line of sight passes above an edge |
| Lateral paths | 7.4.3, factor-8 rule, elevated-ground exclusion | PDF p. 27 | `nb_lateral`, `nb_receiver_3d` | see "Lateral construction" below |
| Combination | (25) `A_bar = -10 lg(sum 10^(-0.1 A_i))`, caps 20 dB (single) / 25 dB (multiple) on the top path | PDF p. 28 | `nb_abar`, `nb_dz` | |
| Wavelength criterion | 7.4.1: object width normal to S-R must exceed lambda | PDF p. 22 | `nb_receiver_3d` | per band, obstacles only |
| `C_met` | (31), (32) | PDF p. 32 | `nb_cmet` | |
| Not implemented | reflections 7.5 (image sources), `A_misc` (Annex A), directivity of chimneys (Annex B), Annex C/D | | | listed in every result as `notImplemented` |

## DRAFT amendment (`draft2026`)

Only the two equations visible in the supplied screenshot `ISO 9613-2 2024 DAmd 1.PNG` are replaced; the rest of the draft was not provided, so nothing else is assumed.

| Eq. | Published 2024 | DRAFT DAmd 1 |
|---|---|---|
| (18) | `D_z = 10 lg[1 + (2 + (C2/lambda) C3 z) K_met]`, `z > z_min` | `D_z = 10 lg[3 + (C2/lambda) C3 z K_met]`, `z > z_min`; 0 otherwise |
| (21) | `K_met = exp{-(1/2000) sqrt([max(dss,dsr)+e] min(dss,dsr) d / [2(z - z_min)])}` | `K_met = exp[-(1/2000) sqrt(dss dsr d / (2 z))]` for `z > 0`; `K_met = 1` for `z <= 0` |

Observation: the DRAFT expressions are identical to ISO 9613-2:1996 Formula (14)/(15) in the stepwise form recommended by ISO/TR 17534-3 cl. 5.4. The published 2024 form is the one that differs from the earlier edition.

## `iso1996` compatibility mode

| Item | Behaviour | Evidence |
|---|---|---|
| `A_atm` | rounded `alpha` at nominal frequencies, 20 degC / 70 % only: 0.1 0.3 1.1 2.8 5.0 9.0 22.9 76.6 dB/km | ISO/TR 17534-3 Tables 4-67 |
| `A_gr` | plain sum `A_s + A_r + A_m` (no `K_geo`) | T01-T03 |
| `D_z` | DRAFT form (3 + ...); `lambda` of the **63 Hz band = 340/62.5** | T16 `C3,top = 1.76` reproduces only with 62.5 Hz |
| Factor-8 rule | **not applied** | T09 includes a lateral path 38 m off the line (limit would be 19 m) |

The last two rows were determined from the reference tables themselves, so they are calibrations to the reference implementation, not independent findings.

## Lateral construction (3D)

Following ISO 9613-2:2024 7.4.3 and ISO/TR 17534-3 cl. 5.2 (the supplied standard states the rules but not the construction):

1. Plane EL contains S and R and is perpendicular to the vertical plane; coordinates `u` (along S-R, 3D) and `v` (horizontal normal).
2. The plane rises or falls from S to R. An obstacle is cut only where the plane is below its roof, so the **plan footprint is clipped** to that half-plane; supports are the clipped footprint's vertices, including the new points where the plane crosses the roof level. (Verified against the published geometry of T12 and T15.)
3. The rubber band starts with the blocking obstacles; any other obstacle the string would cut through is added and the string re-pulled (T17).
4. The 3D result is the pair of left/right paths, combined by (25) with the top path.

Limits: hull-based, exact for convex cross-sections. A concave footprint with a courtyard (T18) needs a visibility-graph search and is **not** supported. Terrain (hills) gets no lateral paths: a raster does not define lateral edges, and 7.4.3 excludes lateral paths when elevated ground contributes to the top path.

## Engineering extensions (labelled in results, not ISO-prescribed)

| Feature | Model | Flag in output |
|---|---|---|
| Transmission through a screen | `A_eff = -10 lg(10^(-A_bar/10) + 10^(-TL/10))` where the opaque `A_bar > 0`; TL measured or mass law | `screen.method` states "NOT prescribed by ISO 9613-2" |
| Mass law | `TL = 20 lg(pi f m / (rho0 c))`, `rho0 c = 415`; floored at 0 | `confidence: rough estimate` |
| Bottom gap of a hanging screen | extra lateral-style path over the bottom edge | `geom.under` |
| Source enclosure | diffuse-field model `L_W,out = L_W,in + 10 lg(4/A) - TL + 10 lg S - 6` | `enclosure.warnings` |
| Octave filters | custom 6th-order Butterworth (Signal Processing Toolbox) | not verified for IEC 61260-1 |
