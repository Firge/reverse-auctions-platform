/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CATALOG_API_MODE?: "mock" | "real";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
