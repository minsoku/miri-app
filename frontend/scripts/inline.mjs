// dist-demo/index.html에 JS·CSS를 인라인해 파일 하나로 만든다(아티팩트·오프라인용).
import { existsSync, readFileSync, writeFileSync, readdirSync } from "fs";
const dir = process.argv[2] || "dist-demo";
let html = readFileSync(`${dir}/index.html`, "utf-8");
html = html.replace(/<script type="module" crossorigin src="\.\/assets\/([^"]+)"><\/script>/, (_, f) => {
  const js = readFileSync(`${dir}/assets/${f}`, "utf-8").replace(/<\/script/gi, "<\\/script");
  return `<script type="module">${js}</script>`;
});
html = html.replace(/<link rel="stylesheet" crossorigin href="\.\/assets\/([^"]+)">/, (_, f) => `<style>${readFileSync(`${dir}/assets/${f}`, "utf-8")}</style>`);
if (/assets\//.test(html)) throw new Error("인라인되지 않은 자산이 남았어요: " + readdirSync(`${dir}/assets`).join(", "));
writeFileSync(`${dir}/miri-demo.html`, html);
console.log(`${dir}/miri-demo.html ${(html.length / 1e6).toFixed(2)} MB`);
// README가 안내하는 서버 없는 데모(docs/demo/miri-demo.html)도 같은 빌드로 맞춘다 — 옛 빌드가 남아 있지 않게
const docsDemo = new URL("../../docs/demo/", import.meta.url);
if (dir === "dist-demo" && existsSync(docsDemo)) {
  writeFileSync(new URL("miri-demo.html", docsDemo), html);
  console.log("docs/demo/miri-demo.html 갱신");
}

// 아티팩트용: 게시 도구가 <html><head><body> 뼈대를 씌우므로 본문만 남긴다(title·style·root·script).
const title = (html.match(/<title>[\s\S]*?<\/title>/) || [""])[0];
const styles = (html.match(/<style>[\s\S]*?<\/style>/g) || []).join("\n");
const script = (html.match(/<script type="module">[\s\S]*?<\/script>/) || [""])[0];
const extra = "<style>.topbar{padding-top:10px}</style>";      // 뼈대가 안전영역 여백을 이미 줌
const fragment = `${title}\n${styles}\n${extra}\n<div id="root"></div>\n${script}\n`;
writeFileSync(`${dir}/miri-demo-artifact.html`, fragment);
console.log(`${dir}/miri-demo-artifact.html ${(fragment.length / 1e6).toFixed(2)} MB`);
