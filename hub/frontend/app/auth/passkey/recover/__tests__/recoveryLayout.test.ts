import fs from "node:fs";
import path from "node:path";

const css = fs.readFileSync(
  path.join(__dirname, "..", "recovery.module.css"),
  "utf8",
);

function rule(selector: string, source = css) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return source.match(new RegExp(\`${escaped}\\s*\\{([^}]*)\\}\`, "s"))?.[1] ?? "";
}

describe("recovery layout scroll contract", () => {
  it("keeps the backup-code acknowledgement reachable on short viewports", () => {
    const resultPanel = rule(".resultPanel");

    expect(resultPanel).toMatch(/max-height:\s*100%/);
    expect(resultPanel).toMatch(/overflow-y:\s*auto/);
  });

  it("allows the document to grow and scroll on narrow viewports", () => {
    const narrowViewport = css.match(
      /@media\s*\(max-width:\s*780px\)\s*\{([\s\S]*?)\n\}/,
    )?.[1] ?? "";
    const page = rule(".page", narrowViewport);

    expect(page).toMatch(/height:\s*auto/);
    expect(page).toMatch(/min-height:\s*100svh/);
    expect(page).toMatch(/overflow:\s*visible/);
  });
});
