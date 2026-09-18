# Virtual Lab Model Card

## Tujuan
Virtual Lab FormulaPilot mensimulasikan gel-krim O/W skincare untuk menguji alur desain eksperimen. Data ini sintetis dan bukan hasil laboratorium.

## Input
Sepuluh bahan pada `data/assumptions/ingredients.csv`, parameter RPM/HMIN/TEMP, dan AQUA sebagai balance hingga 100%.

## Persamaan
Simulator menghitung `OIL = CCT + DIMETHICONE + 0.5*CETEARYL_ALCOHOL`, `EMUL = EMULSIFIER + 0.3*CETEARYL_ALCOHOL`, serta derajat netralisasi carbomer. pH, log10 viskositas, droplet D50, stabilitas, dan biaya mengikuti persamaan terbuka pada PRD §8.1.2. Implementasi ada di `fp/virtual_lab.py`.

- v1: persamaan dasar dengan noise pengukuran.
- v2: koefisien numerik diskalakan U(0.75, 1.25), seed 2.
- v3: interaksi glycerin-stability dan dimethicone-droplet, noise 1,5 kali.

## Kalibrasi dan evaluasi
Angka kalibrasi harus dibaca dari `data/virtual_lab/generation_manifest.json` atau `artifacts/evaluation.json`; tidak ditulis manual di UI. Generator memakai seed 20260917 dan menghasilkan 400 record per varian.

## Batasan
Simulator tidak membuktikan keamanan, kepatuhan, efikasi, stabilitas umur simpan, atau performa produk nyata. `true_mean` hanya untuk test/model card; jalur aplikasi memakai `run_batch`. Dataset liposom hanya validasi metode terpisah dan tidak dipakai training skincare.

## Penggantian dengan data lab
Data internal dapat menggantikan CSV sintetis bila mengikuti skema formula + parameter proses + output VISCOSITY_CP, PH, D50_UM, STABILITY_INDEX, STABLE, COST_IDR_PER_KG, dan variant/source.
