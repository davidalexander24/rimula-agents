import { TriangleAlert } from 'lucide-react';
import type { Envelope, Health } from '../../api/types';
export function DegradedBanner({ result }: { result?: Envelope<Health> }) {
  if (result?.mode !== 'degraded') return null;
  const { model_ready, llm_ready } = result.data;
  const description = !model_ready
    ? 'Model prediksi belum siap. Eksperimen dapat dijalankan setelah model tersedia.'
    : !llm_ready ? 'LLM belum siap. Eksperimen dapat menggunakan alur deterministik dan ringkasan otomatis.'
    : 'Sebagian layanan belum siap. Periksa rincian status sistem.';
  return <div className="degraded-banner" role="status"><TriangleAlert size={19} /><div><strong>Mode terbatas</strong><span>{description}</span></div></div>;
}
