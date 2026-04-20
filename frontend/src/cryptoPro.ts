import type { CryptoCertificateInfo } from "./types";

type CadesPlugin = {
  CreateObjectAsync: (name: string) => unknown;
  async_spawn: (generatorFn: () => Generator<unknown, void, unknown>) => void;
  CAPICOM_CURRENT_USER_STORE?: number;
  CAPICOM_MY_STORE?: string;
  CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED?: number;
  CAPICOM_CERTIFICATE_FIND_SHA1_HASH?: number;
  CADESCOM_CADES_BES?: number;
};

declare global {
  interface Window {
    cadesplugin?: CadesPlugin | Promise<unknown>;
  }
}

const SCRIPT_SOURCES = [
  "/cadesplugin_api.js",
  "https://www.cryptopro.ru/sites/default/files/products/cades/cadesplugin_api.js",
];

function toErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error ?? "Неизвестная ошибка");
}

async function loadScript(src: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const existing = document.querySelector(`script[data-cades-src=\"${src}\"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.cadesSrc = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Не удалось загрузить ${src}`));
    document.head.appendChild(script);
  });
}

function getCadesPluginObject(): CadesPlugin {
  const plugin = window.cadesplugin as CadesPlugin | Promise<unknown> | undefined;
  if (
    plugin
    && typeof plugin === "object"
    && "CreateObjectAsync" in plugin
    && "async_spawn" in plugin
  ) {
    return plugin as CadesPlugin;
  }
  throw new Error("Плагин КриптоПро не инициализирован.");
}

async function ensureCadesPlugin(): Promise<void> {
  if (!window.cadesplugin) {
    let lastError: unknown = null;
    for (const src of SCRIPT_SOURCES) {
      try {
        await loadScript(src);
        if (window.cadesplugin) break;
      } catch (error) {
        lastError = error;
      }
    }
    if (!window.cadesplugin) {
      throw new Error(`Плагин КриптоПро не найден. ${toErrorMessage(lastError)}`);
    }
  }

  const cadesplugin = window.cadesplugin;
  if (cadesplugin && typeof (cadesplugin as Promise<unknown>).then === "function") {
    await (cadesplugin as Promise<unknown>);
  }
  getCadesPluginObject();
}

function runCadesTask<T>(
  task: (cadesplugin: CadesPlugin) => Generator<unknown, T, unknown>,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let cadesplugin: CadesPlugin;
    try {
      cadesplugin = getCadesPluginObject();
    } catch (error) {
      reject(error);
      return;
    }
    if (!cadesplugin) {
      reject(new Error("Плагин КриптоПро не загружен."));
      return;
    }

    try {
      cadesplugin.async_spawn(function* () {
        try {
          const result = yield* task(cadesplugin);
          resolve(result);
        } catch (error) {
          reject(error);
        }
      });
    } catch (error) {
      reject(error);
    }
  });
}

export async function listCryptoProCertificates(): Promise<CryptoCertificateInfo[]> {
  await ensureCadesPlugin();
  const cadesplugin = getCadesPluginObject();
  const CAPICOM_CURRENT_USER_STORE = cadesplugin.CAPICOM_CURRENT_USER_STORE ?? 2;
  const CAPICOM_MY_STORE = cadesplugin.CAPICOM_MY_STORE ?? "My";
  const CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED = cadesplugin.CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED ?? 2;

  return runCadesTask<CryptoCertificateInfo[]>(function* (cp) {
    const store = (yield cp.CreateObjectAsync("CAdESCOM.Store")) as {
      Open: (location: number, name: string, mode: number) => unknown;
      Close: () => unknown;
      Certificates: unknown;
    };

    try {
      yield store.Open(CAPICOM_CURRENT_USER_STORE, CAPICOM_MY_STORE, CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED);
      const certificates = (yield store.Certificates) as {
        Count: unknown;
        Item: (index: number) => unknown;
      };
      const count = Number(yield certificates.Count);
      const result: CryptoCertificateInfo[] = [];

      for (let i = 1; i <= count; i += 1) {
        const cert = (yield certificates.Item(i)) as {
          Thumbprint: unknown;
          SubjectName: unknown;
          IssuerName: unknown;
          ValidFromDate: unknown;
          ValidToDate: unknown;
          HasPrivateKey: () => unknown;
        };
        const hasPrivateKey = Boolean(yield cert.HasPrivateKey());
        if (!hasPrivateKey) continue;
        result.push({
          thumbprint: String(yield cert.Thumbprint),
          subjectName: String(yield cert.SubjectName),
          issuerName: String(yield cert.IssuerName),
          validFrom: String(yield cert.ValidFromDate),
          validTo: String(yield cert.ValidToDate),
        });
      }

      return result;
    } finally {
      try {
        yield store.Close();
      } catch {
        // Ignore close errors from browser plugin.
      }
    }
  });
}

export async function signWithCryptoPro(documentText: string, certThumbprint: string): Promise<string> {
  await ensureCadesPlugin();
  const cadesplugin = getCadesPluginObject();
  const CAPICOM_CURRENT_USER_STORE = cadesplugin.CAPICOM_CURRENT_USER_STORE ?? 2;
  const CAPICOM_MY_STORE = cadesplugin.CAPICOM_MY_STORE ?? "My";
  const CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED = cadesplugin.CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED ?? 2;
  const CAPICOM_CERTIFICATE_FIND_SHA1_HASH = cadesplugin.CAPICOM_CERTIFICATE_FIND_SHA1_HASH ?? 0;
  const CADESCOM_CADES_BES = cadesplugin.CADESCOM_CADES_BES ?? 1;

  if (!documentText.trim()) {
    throw new Error("Документ пустой, подписывать нечего.");
  }

  return runCadesTask<string>(function* (cp) {
    const store = (yield cp.CreateObjectAsync("CAdESCOM.Store")) as {
      Open: (location: number, name: string, mode: number) => unknown;
      Close: () => unknown;
      Certificates: unknown;
    };

    try {
      yield store.Open(CAPICOM_CURRENT_USER_STORE, CAPICOM_MY_STORE, CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED);
      const allCerts = (yield store.Certificates) as {
        Find: (findType: number, criteria: string) => unknown;
      };
      const foundCerts = (yield allCerts.Find(CAPICOM_CERTIFICATE_FIND_SHA1_HASH, certThumbprint)) as {
        Count: unknown;
        Item: (index: number) => unknown;
      };
      const count = Number(yield foundCerts.Count);
      if (!count) {
        throw new Error("Сертификат не найден в локальном хранилище.");
      }

      const cert = yield foundCerts.Item(1);
      const signer = (yield cp.CreateObjectAsync("CAdESCOM.CPSigner")) as {
        propset_Certificate: (certificate: unknown) => unknown;
        propset_CheckCertificate: (value: boolean) => unknown;
      };
      yield signer.propset_Certificate(cert);
      yield signer.propset_CheckCertificate(true);

      const signedData = (yield cp.CreateObjectAsync("CAdESCOM.CadesSignedData")) as {
        propset_Content: (content: string) => unknown;
        SignCades: (signer: unknown, signatureType: number, detached: boolean) => unknown;
      };
      yield signedData.propset_Content(documentText);

      const signature = String(yield signedData.SignCades(signer, CADESCOM_CADES_BES, true));
      if (!signature) {
        throw new Error("Плагин вернул пустую подпись.");
      }
      return signature;
    } finally {
      try {
        yield store.Close();
      } catch {
        // Ignore close errors from browser plugin.
      }
    }
  });
}
