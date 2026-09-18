# Explainer Marshal

Marshal mengembangkan palet bahan, Virtual Lab, generator data sintetis, Designer GP, evaluasi, dan validasi liposom. Designer memakai Gaussian Process karena data formulasi biasanya kecil dan model memberi interval ketidakpastian. Formula diusulkan dari ruang valid, lalu diprioritaskan dengan peluang memenuhi spesifikasi dan diversity. Hasil Virtual Lab dipisahkan dari data liposom nyata: liposom hanya untuk validasi metode. Semua angka demo wajib dibaca dari artefak evaluasi.

```text
brief -> palette -> Virtual Lab/historical -> GP prediction + uncertainty
      -> candidate ranking -> lab result -> retrain -> next candidate
```

## Pertanyaan juri
1. **Mengapa data sintetis?** Virtual Lab terdokumentasi dan sengaja dipakai sebagai dummy; pilot menggantinya dengan catatan lab internal.
2. **Mengapa GP?** GP cocok untuk dataset kecil dan menyediakan ketidakpastian untuk memilih eksperimen berikutnya.
3. **Apakah hasilnya bukti lab?** Tidak. Hasil Virtual Lab adalah simulasi; kandidat tetap perlu diuji di laboratorium.

## Batasan
Simulator bukan pengganti laboratorium. Angka biaya adalah asumsi. Validasi liposom berasal dari domain berbeda sehingga tidak boleh dibaca sebagai validasi produk skincare.


## Artefak verifikasi terbaru
Angka evaluasi dibaca dari `artifacts/evaluation.json`; evaluasi penuh mencakup CV, closed-loop tiga varian, replay historis, validasi liposom, estimasi simulasi, dan lima figur.
