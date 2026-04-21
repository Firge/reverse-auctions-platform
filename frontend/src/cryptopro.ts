import { createAttachedSignature, getUserCertificates, type Certificate } from "crypto-pro";
import type { CryptoCertificateInfo } from "./types";

function normalizeCryptoError(error: unknown) {
  if (error instanceof Error && error.message) return error.message;
  return String(error ?? "Неизвестная ошибка КриптоПро");
}

export async function listCryptoProCertificates(): Promise<CryptoCertificateInfo[]> {
  try {
    const certs: Certificate[] = await getUserCertificates(true);
    return certs.map((cert) => ({
      thumbprint: cert.thumbprint,
      subjectName: cert.subjectName,
      issuerName: cert.issuerName,
      validFrom: cert.validFrom,
      validTo: cert.validTo,
    }));
  } catch (error) {
    throw new Error(`Не удалось получить сертификаты: ${normalizeCryptoError(error)}`);
  }
}

export async function signWithCryptoPro(documentText: string, certThumbprint: string): Promise<string> {
  if (!documentText.trim()) {
    throw new Error("Документ пустой, подписывать нечего.");
  }
  if (!certThumbprint.trim()) {
    throw new Error("Не выбран сертификат для подписи.");
  }

  try {
    return await createAttachedSignature(certThumbprint, documentText);
  } catch (error) {
    throw new Error(`Не удалось подписать документ: ${normalizeCryptoError(error)}`);
  }
}
