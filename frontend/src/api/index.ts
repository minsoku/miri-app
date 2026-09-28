import type { Api } from "./types";
import { createHttpApi } from "./http";

// 빌드 모드에 따라 실서버 API 또는 브라우저 내 데모 API를 쓴다.
let api: Api | null = null;
export async function getApi(): Promise<Api> {
  if (api) return api;
  if (import.meta.env.MODE === "demo") {
    const { createDemoApi } = await import("./demo/demoApi");
    api = await createDemoApi();
  } else {
    api = createHttpApi();
  }
  return api;
}
export * from "./types";
