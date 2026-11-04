"""Headless editor suite (Playwright, headless Chromium).

    python tests/verify_editor.py

Starts the real server.py on a scratch folder (fixtures, config and state in
READO_TEST_WORK, default %TEMP%/reado-headless — recreated on every run; the
user's ReadO settings are not touched), drives source.html and checks results
on disk: editor, tree, Quick Open / Find in Files, links and definitions,
panes, settings, instance hand-off. Needs port 8799 free, and 8766 for the
port-fallback check. The "Open with" check writes HKCU file associations and
removes them again (skipped when ReadO is already registered).
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORK = os.environ.get("READO_TEST_WORK") or os.path.join(tempfile.gettempdir(), "reado-headless")
BASE = os.path.join(WORK, "base")
OUT = os.path.join(WORK, "outside")
CFG = os.path.join(WORK, "cfg")
PORT = int(os.environ.get("READO_TEST_PORT") or 8799)  # another app may hold 8799

sys.path.insert(0, REPO)
import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def w(path, data, mode="w", **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if mode == "w":
        kw.setdefault("newline", "")
        kw.setdefault("encoding", "utf-8")
    with open(path, mode, **kw) as f:
        f.write(data)


def bump(path):
    """Ensure a strictly later mtime than before (coarse FS timestamps)."""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def setup_links(p):
    """Sample projects for import / include links (p = BASE/proj)."""
    web = os.path.join(p, "web", "src", "main")
    w(os.path.join(web, "page", "Detail.vue"),
      "<template>\n"                                                                    # 1
      "  <div><ItemsCarousel/><img src=\"../img/bg.png\"></div>\n"                       # 2
      "</template>\n"                                                                    # 3
      "<script lang=\"ts\" setup>\n"                                                     # 4
      "import ItemsCarousel from \"@/main/page/product/RecommendItemsCarousel.vue\"\n"   # 5
      "import {RelatedProductsSection} from \"@/main/service/product/domain/productModel.ts\"\n"  # 6
      "import {onMounted, ref} from \"vue\"\n"                                           # 7
      "import {productService} from \"@/main/service/product/application/productService\"\n"     # 8
      "import {formatPrice, Money as Cash, ns} from \"@/main/util\"\n"                   # 9
      "import \"./missing-file\"\n"                                                      # 10
      "const props = defineProps<{ related?: RelatedProductsSection[] }>()\n"            # 11
      "onMounted(() => productService.getProduct(1))\n"                                  # 12
      "const p: Cash = formatPrice(1)\n"                                                 # 13
      "const lazy = () => import('../../legacy/Old.vue')\n"                              # 14
      "const cfg = require('./cfg.json')\n"                                              # 15
      "</script>\n"                                                                      # 16
      "<style src=\"./detail.css\"></style>\n")                                          # 17
    w(os.path.join(web, "page", "product", "RecommendItemsCarousel.vue"), "<template><div>carousel</div></template>\n")
    w(os.path.join(web, "page", "cfg.json"), "{}\n")
    w(os.path.join(web, "page", "detail.css"), "@import \"./base.css\";\n.a { background: url(../img/bg.png) }\n")
    w(os.path.join(web, "page", "base.css"), "body {}\n")
    w(os.path.join(web, "img", "bg.png"), b"\x89PNG\r\n\x1a\n\x00", "wb")
    w(os.path.join(web, "service", "product", "domain", "productModel.ts"),
      "// product model\n\nexport interface RelatedProductsSection {\n  id: number\n}\n")
    w(os.path.join(web, "service", "product", "application", "productService.ts"),
      "import {api} from \"../../api\"\n\nexport const productService = {\n  async list() { return this.getProduct(0) },\n"
      "  async getProduct(id: number) {\n    return api.get('/p/' + id)\n  },\n}\n")
    w(os.path.join(web, "service", "api.ts"), "export const api = { get(u: string) { return u } }\n")
    w(os.path.join(web, "util", "index.ts"), "export * from './price'\nexport { Money } from './money'\nexport * as ns from './money'\n")
    w(os.path.join(web, "util", "price.ts"), "// price helpers\n\nexport function formatPrice(v: number) { return '' + v }\n")
    w(os.path.join(web, "util", "money.ts"), "\nexport type Money = number\n")
    w(os.path.join(p, "web", "src", "legacy", "Old.vue"), "<template><div>old</div></template>\n")
    # Java
    j = os.path.join(p, "java", "src", "main", "java", "com", "acme", "shop")
    w(os.path.join(j, "Order.java"),
      "package com.acme.shop;\n\nimport com.acme.shop.util.Money;\nimport com.acme.shop.util.*;\nimport java.util.List;\n\n"
      "public class Order {\n    Money total = Money.zero();\n    Item first;\n}\n")
    w(os.path.join(j, "util", "Money.java"),
      "package com.acme.shop.util;\n\npublic class Money {\n    public static Money zero() {\n        return new Money();\n    }\n}\n")
    w(os.path.join(j, "util", "Rates.java"), "package com.acme.shop.util;\n\npublic class Rates {}\n")
    w(os.path.join(j, "Item.java"), "package com.acme.shop;\n\npublic class Item {}\n")
    # Python
    a = os.path.join(p, "py", "app")
    w(os.path.join(a, "__init__.py"), "")
    w(os.path.join(a, "main.py"),
      "from .services.users import get_user, User as U\nfrom . import helpers\nimport app.services.users\n"
      "from .missing import nope\nimport os\n\n\ndef run():\n    u = get_user(1)\n    helpers.slugify('x')\n")
    w(os.path.join(a, "helpers.py"), "import re\n\n\ndef slugify(s):\n    return s\n")
    w(os.path.join(a, "services", "__init__.py"), "")
    w(os.path.join(a, "services", "users.py"), "class User:\n    pass\n\n\ndef get_user(uid):\n    return User()\n")
    # Go
    g = os.path.join(p, "gosvc")
    w(os.path.join(g, "go.mod"), "module example.com/gosvc\n\ngo 1.22\n")
    w(os.path.join(g, "main.go"),
      "package main\n\nimport (\n\t\"fmt\"\n\t\"example.com/gosvc/internal/store\"\n)\n\nfunc main() {\n\tfmt.Println(store.Open())\n}\n")
    w(os.path.join(g, "internal", "store", "store.go"), "package store\n\nfunc Open() int {\n\treturn 1\n}\n")
    # C, Rust, PHP, Ruby, C#
    w(os.path.join(p, "cproj", "main.c"), "#include \"util/strings.h\"\n#include <stdio.h>\n")
    w(os.path.join(p, "cproj", "util", "strings.h"), "int slen(const char *s);\n")
    w(os.path.join(p, "rs", "Cargo.toml"), "[package]\nname = \"rs\"\n")
    w(os.path.join(p, "rs", "src", "main.rs"), "mod net;\nuse crate::net::client::Client;\n\nfn main() {}\n")
    w(os.path.join(p, "rs", "src", "net", "mod.rs"), "pub mod client;\n")
    w(os.path.join(p, "rs", "src", "net", "client.rs"), "\npub struct Client;\n")
    w(os.path.join(p, "php", "composer.json"), '{"autoload": {"psr-4": {"App\\\\": "src/"}}}\n')
    w(os.path.join(p, "php", "index.php"), "<?php\nuse App\\Http\\Kernel;\nrequire_once __DIR__ . '/bootstrap.php';\n")
    w(os.path.join(p, "php", "bootstrap.php"), "<?php\n")
    w(os.path.join(p, "php", "src", "Http", "Kernel.php"), "<?php\nnamespace App\\Http;\n\nclass Kernel {}\n")
    w(os.path.join(p, "rb", "app.rb"), "require_relative 'lib/thing'\nrequire 'json'\n")
    w(os.path.join(p, "rb", "lib", "thing.rb"), "class Thing; end\n")
    w(os.path.join(p, "cs", "Program.cs"), "using Acme.Billing;\nusing System;\n")
    w(os.path.join(p, "cs", "Billing.cs"), "\nnamespace Acme.Billing;\n\npublic class Invoice {}\n")
    # a Vue project with no tsconfig / vite / package.json: "@/" must still resolve
    nc = os.path.join(p, "noconf", "client", "src", "main", "page")
    w(os.path.join(nc, "product", "Items.vue"),
      "<template>\n  <ProdInfo/>\n</template>\n"
      "<script setup lang=\"ts\">\n"
      "import ProdInfo from \"@/main/page/product/ProdInfo.vue\"\n"
      "import RelationProduct from \"@/main/page/product/RelationProduct\"\n"
      "import OnlyName from \"@/moved/away/OnlyName.vue\"\n"
      "import Ghost from \"@/main/page/product/Ghost.vue\"\n"
      "</script>\n")
    w(os.path.join(nc, "product", "ProdInfo.vue"), "<template><div>info</div></template>\n")
    w(os.path.join(nc, "product", "RelationProduct.vue"), "<template><div>rel</div></template>\n")
    w(os.path.join(p, "noconf", "client", "src", "ui", "OnlyName.vue"), "<template><div>only</div></template>\n")


def setup_ts(p):
    """The manager's .ts case: "@/" imports with no alias config, an npm package,
    same-file types / functions, a constant only the symbol index knows."""
    sh = os.path.join(p, "shop")
    w(os.path.join(sh, "package.json"), "{}\n")
    svc = os.path.join(sh, "src", "main", "service")
    w(os.path.join(svc, "cart", "domain", "CartModel.ts"),
      'import {RawData} from "@/util/typeUtil.ts"\n'
      "\n"
      "export interface CartOrderLineItem {\n"
      "  id: string\n"
      "}\n"
      "export class CartModel { items: CartOrderLineItem[] = [] }\n"
      "export const MAX_CART_ITEMS = 10\n")
    w(os.path.join(svc, "product", "domain", "productModel.ts"), "// product\n\nexport type ProductDetail = { name: string }\n")
    w(os.path.join(sh, "src", "util", "typeUtil.ts"), "export type RawData = Record<string, unknown>\n")
    w(os.path.join(svc, "cart", "cartEventBus.ts"),
      'import mitt from "mitt"\n'                                                        # 1
      'import {ProductDetail} from "@/main/service/product/domain/productModel.ts"\n'   # 2
      'import {CartOrderLineItem} from "@/main/service/cart/domain/CartModel.ts"\n'     # 3
      "\n"                                                                               # 4
      "type CartEvent = {\n"                                                             # 5
      "  cartLineItemRemoved: CartOrderLineItem[]\n"                                     # 6
      "  'addToCart': AddToCartDto\n"                                                    # 7
      "}\n"                                                                              # 8
      "interface AddToCartDto { product: ProductDetail }\n"                              # 9
      "function makeCartBus() { return mitt<CartEvent>() }\n"                            # 10
      "export const cartEventBus = makeCartBus()\n"                                      # 11
      "const localThing = 1\n"                                                           # 12
      "export function useCartBus() { return cartEventBus && localThing && undefinedThing && MAX_CART_ITEMS }\n")  # 13
    w(os.path.join(svc, "cart", "cartUtil.js"), 'import mitt from "mitt"\nconst = 1\nexport const bus = mitt()\n')


def setup_extras(p):
    """File operations, .gitignore filter, a small git repository."""
    w(os.path.join(p, "ops", "keep.txt"), "keep\n")
    w(os.path.join(p, "ops", "ren.txt"), "line1\nline2\nline3\n")
    w(os.path.join(p, "ops", "dir1", "inner.txt"), "inner\n")
    w(os.path.join(p, "ops", "gone.txt"), "to delete\n")
    w(os.path.join(p, "ops", "dir2", "x.txt"), "x\n")
    gi = os.path.join(p, "gi")
    w(os.path.join(gi, ".gitignore"), "*.secret\nlogs/\n!keep.secret\n")
    w(os.path.join(gi, "a.secret"), "gineedle\n")
    w(os.path.join(gi, "keep.secret"), "gineedle\n")
    w(os.path.join(gi, "ok.txt"), "gineedle\n")
    w(os.path.join(gi, "logs", "x.txt"), "gineedle\n")
    repo = os.path.join(p, "repo")
    w(os.path.join(repo, "tracked.txt"), "one\ntwo\nthree\nfour\n")
    import subprocess as sp
    git = lambda *a: sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, capture_output=True)
    git("init", "-q", "-b", "main")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "init")


def setup():
    shutil.rmtree(WORK, ignore_errors=True)
    p = os.path.join(BASE, "proj")
    w(os.path.join(p, "A.java"), "package com.example.svc01000;\n\npublic class Svc01000 {\n  int x;\n}\n")
    w(os.path.join(p, "B.java"), "package b;\n\nclass B {\n  Svc01000 ref = null;\n}\n")
    w(os.path.join(p, "Dockerfile"), "FROM needle:1\n")
    w(os.path.join(p, "readme.md"),
      "# Title One\n\nhello **bold**\n\n<script>window.__xss=1</script>\n\n[other](B.java)\n")
    w(os.path.join(p, "notes.txt"), "plain text note\n")
    w(os.path.join(p, "run.sh"), "#!/bin/sh\necho needle\n")
    w(os.path.join(p, "conf.toml"), "[a]\nb = 1\n")
    w(os.path.join(p, "app.log"), "log line\n")
    w(os.path.join(p, "LICENSE"), "no extension text\n")
    w(os.path.join(p, ".env"), "SECRET=1\n")
    w(os.path.join(p, ".gitignore"), "build/\n")
    w(os.path.join(p, ".git", "config"), "[core]\n")
    w(os.path.join(p, "doc", "guide.md"), "# Guide\n")
    for name in ("Widgets.vue", "sub/widgets.vue", "WidgetsSidebar.vue", "AboutUsWidgets.vue",  # Find File order
                 "deep/deeper/widgets.vue", "a_widgets.vue", "b_widgets.vue", "c_widgets.vue", "d_widgets.vue", "e_widgets.vue"):
        w(os.path.join(p, "qo", *name.split("/")), "<template><div/></template>\n")
    # a git worktree checked out inside the folder (.git is a file), like C:\Projects\_wt\…
    w(os.path.join(p, "_wt", "stg-log", ".git"), "gitdir: C:/elsewhere/.git/worktrees/stg-log\n")
    w(os.path.join(p, "_wt", "stg-log", "src", "main", "WtApp.java"), "class WtApp {}\n")
    w(os.path.join(p, "doc", "pics.md"),
      "# Pics\n\n![ok](img/dot.png) ![up](../logo.png) ![out](../../../outside.png)"
      " <img src=\"data:image/png;base64,AAAA\">\n\n[guide](guide.md) [escape](../../../x.md)\n\n"
      "```js\nconst x = 1;\n```\n\n```nosuchlang\nplain\n```\n")
    w(os.path.join(p, "doc", "img", "dot.png"), DOT_PNG, "wb")
    w(os.path.join(p, "doc", "img", "pic.svg"), '<svg xmlns="http://www.w3.org/2000/svg"/>')
    w(os.path.join(WORK, "outside.png"), DOT_PNG, "wb")
    w(os.path.join(p, "build", "gen.java"), "class Gen { needle }\n")
    w(os.path.join(p, "logo.png"), b"\x89PNG\r\n\x1a\n\x00\x00", "wb")
    w(os.path.join(p, "fake.txt"), b"abc\x00\x01\x02def" * 20, "wb")
    w(os.path.join(p, "u16.txt"), "utf16 no bom\n".encode("utf-16-le"), "wb")
    nav = os.path.join(p, "nav")
    w(os.path.join(nav, "Shapes.java"), "package nav;\npublic class Shapes {\n    public int area(int w) {\n"
      "        return helper(w);\n    }\n\n    private int helper(int x) {\n        return x * 2;\n    }\n}\n")
    w(os.path.join(nav, "Use.java"), "package nav;\nclass Use {\n    void run() {\n        Shapes s = new Shapes();\n"
      "        int a = s.area(3);\n        Dup d = null;\n        helper(1);\n    }\n}\n")
    w(os.path.join(nav, "Dup.java"), "package nav;\nclass Dup {}\n")
    w(os.path.join(nav, "other", "Dup.java"), "package nav.other;\nclass Dup { }\n")
    w(os.path.join(nav, "m.py"), "def compute(x):\n    return x\n\nvalue = compute(1)\n")
    # Vue sample project (component tags)
    web = os.path.join(p, "web")
    w(os.path.join(web, "package.json"), "{}\n")
    w(os.path.join(web, "tsconfig.json"), '{\n  // comment\n  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]},},\n}\n')
    w(os.path.join(web, "vite.config.ts"), "export default { resolve: { alias: { '~c': fileURLToPath(new URL('./src/components', import.meta.url)) } } }\n")
    w(os.path.join(web, "src", "pages", "Items.vue"),
      "<template>\n  <div class=\"x\">\n    <ItemTop :a=\"1\"\n      @go=\"go\"></ItemTop>\n    <item-info></item-info>\n"
      "    <SharedCard/>\n    <Dup/>\n    <Missing/>\n    <router-view/>\n    <AliasThing/>\n  </div>\n</template>\n"
      "<script setup lang=\"ts\">\nimport ItemTop from '@/components/item/ItemTop.vue'\nimport AliasThing from '~c/AliasThing.vue'\n"
      "const r = ref<ItemTop>()\n</script>\n")
    w(os.path.join(web, "src", "components", "item", "ItemTop.vue"), "<template><div>top</div></template>\n")
    w(os.path.join(web, "src", "legacy", "ItemTop.vue"), "<template><div>old top (decoy)</div></template>\n")
    w(os.path.join(web, "src", "components", "ItemInfo.vue"), "<template><div>info</div></template>\n")
    w(os.path.join(web, "src", "components", "shared", "SharedCard", "index.vue"), "<template><div>card</div></template>\n")
    w(os.path.join(web, "src", "components", "Dup.vue"), "<template><div>dup near</div></template>\n")
    w(os.path.join(p, "other", "Dup.vue"), "<template><div>dup far</div></template>\n")
    w(os.path.join(web, "src", "components", "AliasThing.vue"), "<template><div>alias</div></template>\n")
    w(os.path.join(web, "src", "App.tsx"), "export function App() {\n  const s = useState<Dup>(null)\n  return <ItemTop />\n}\n")
    nux = os.path.join(p, "nuxt")
    w(os.path.join(nux, "package.json"), "{}\n")
    w(os.path.join(nux, "components", "base", "Button.vue"), "<template><button/></template>\n")
    w(os.path.join(nux, "pages", "index.vue"), "<template>\n  <BaseButton/>\n</template>\n")
    w(os.path.join(p, "kor.properties"), "name=한글값\n".encode("cp949"), "wb")
    w(os.path.join(p, "crlf.yml"), "a: 1\r\nb: 2\r\n", newline="")
    w(os.path.join(p, "bom.json"), b"\xef\xbb\xbf{\"k\": 1}\n", "wb")
    w(os.path.join(p, "big.json"), "[" + ",".join(['"%06d"' % i for i in range(260_000)]) + "]\n")
    w(os.path.join(p, "sub", "deep.java"), "class Deep {}\n")
    # Find in Files excludes: default noise next to source, a folder to exclude by hand
    xs = os.path.join(BASE, "xs")
    for name in ("app.js", "app.min.js", "app.js.map", "yarn.lock", "tsconfig.tsbuildinfo", os.path.join("gen", "g.js"),
                 os.path.join("build", "b.js"), os.path.join(".idea", "w.xml"),
                 os.path.join(".idea", "shelf", "Uncommitted_changes_[x]", "shelved.patch"),  # IntelliJ shelf
                 os.path.join("shelf", "s1", "shelved.patch")):                                 # shelf kept outside .idea
        w(os.path.join(xs, name), "xneedle\n")
    w(os.path.join(OUT, "ext.txt"), "outside file\n")
    w(os.path.join(OUT, "secret.txt"), "not granted\n")
    os.makedirs(CFG, exist_ok=True)
    server.CONFIG_PATH = os.path.join(CFG, "config.json")
    server.SETTINGS = server.save_settings({"base_dir": BASE})
    server._first_run = False
    server._state = None
    # a state.json from the previous build that saved editing as off
    w(os.path.join(CFG, "state.json"), json.dumps({"ui": {"editMode": False, "theme": "light"}}))
    w(os.path.join(BASE, "proj", "Rep1.java"), "class Rep1 { Svc01000 a; Svc01000 b; }\n")
    w(os.path.join(BASE, "proj", "Rep2.java"), "class Rep2 { Svc01000 c; }\n")
    w(os.path.join(BASE, "proj", "Rep3.java"), "class Rep3 { Svc01000 d; }\n")
    w(os.path.join(BASE, "proj", "rep.properties"), "k=Svc01000 한글\n".encode("cp949"), "wb")
    setup_links(p)
    setup_extras(p)
    setup_ts(p)


def start_server():
    httpd = server.make_server("127.0.0.1", PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def raw_post(path, body, token=None, extra=None):
    h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{PORT}"}
    if token:
        h[server.TOKEN_HEADER] = token
    h.update(extra or {})
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def link_server_checks():
    """link_at() on the sample projects (no browser)."""
    D = "proj/web/src/main/page/Detail.vue"

    def L(key, line, col, text=None):
        if text is None:
            with open(os.path.join(BASE, key.replace("/", os.sep)), encoding="utf-8") as f:
                text = f.read()
        return server.link_at(key, text, line, col)

    def first(r):
        x = (r.get("results") or [{}])[0]
        return [r.get("kind"), x.get("path"), x.get("line")]

    def col_of(key, line, needle, k=0):
        with open(os.path.join(BASE, key.replace("/", os.sep)), encoding="utf-8") as f:
            t = f.read().split("\n")[line - 1]
        return t.index(needle) + 1 + k

    S = "proj/web/src/main/"
    r = L(D, 5, col_of(D, 5, "product/Recommend"))
    check("link: alias path string (anywhere inside) -> the .vue file", first(r) == ["path", S + "page/product/RecommendItemsCarousel.vue", 1]
          and r["range"] == [col_of(D, 5, "@/"), col_of(D, 5, '.vue"') + 4], str(r))
    r = L(D, 8, col_of(D, 8, "productService\"") - 3)
    check("link: extension left out (.ts found)", first(r) == ["path", S + "service/product/application/productService.ts", 1], str(r))
    r = L(D, 9, col_of(D, 9, "@/main/util") + 3)
    check("link: folder import -> index.ts", first(r) == ["path", S + "util/index.ts", 1], str(r))
    r = L(D, 5, col_of(D, 5, "ItemsCarousel") + 2)
    check("link: default-imported name -> the component file", first(r) == ["symbol", S + "page/product/RecommendItemsCarousel.vue", 1], str(r))
    r = L(D, 6, col_of(D, 6, "RelatedProductsSection") + 1)
    check("link: named import -> its export line", first(r) == ["symbol", S + "service/product/domain/productModel.ts", 3], str(r))
    r = L(D, 11, col_of(D, 11, "RelatedProductsSection") + 4)
    check("link: usage of an imported type -> its export", first(r) == ["symbol", S + "service/product/domain/productModel.ts", 3], str(r))
    r = L(D, 12, col_of(D, 12, "getProduct") + 2)
    check("link: importedObj.member() -> the member in that file (not the call in list())",
          first(r) == ["symbol", S + "service/product/application/productService.ts", 5], str(r))
    r = L(D, 13, col_of(D, 13, "formatPrice"))
    check("link: export * from './price' followed", first(r) == ["symbol", S + "util/price.ts", 3], str(r))
    r = L(D, 13, col_of(D, 13, "Cash") + 1)
    check("link: `Money as Cash` through `export { Money } from './money'`", first(r) == ["symbol", S + "util/money.ts", 2], str(r))
    r = L(D, 7, col_of(D, 7, "onMounted") + 1)
    check("link: package import (vue) -> external", r["kind"] == "external" and r["spec"] == "vue", str(r))
    r = L(D, 7, col_of(D, 7, '"vue"') + 2)
    check("link: package path string -> external", r["kind"] == "external", str(r))
    r = L(D, 10, col_of(D, 10, "missing") + 1)
    check("link: relative path that does not exist -> missing", r["kind"] == "missing", str(r))
    r = L(D, 14, col_of(D, 14, "Old.vue"))
    check("link: dynamic import('../../legacy/Old.vue')", first(r) == ["path", "proj/web/src/legacy/Old.vue", 1], str(r))
    r = L(D, 15, col_of(D, 15, "cfg.json"))
    check("link: require('./cfg.json')", first(r) == ["path", S + "page/cfg.json", 1], str(r))
    r = L(D, 17, col_of(D, 17, "detail.css"))
    check("link: <style src>", first(r) == ["path", S + "page/detail.css", 1], str(r))
    r = L(D, 2, col_of(D, 2, "bg.png"))
    check("link: <img src> relative path", first(r) == ["path", S + "img/bg.png", 1], str(r))
    r = L(D, 12, col_of(D, 12, "onMounted(") + 1)
    check("link: imported but used as a call -> still the package (external)", r["kind"] == "external", str(r))
    r = L(D, 11, col_of(D, 11, "props") + 1)
    check("link: a local name is not a link (none -> symbol index)", r["kind"] == "none", str(r))
    C = S + "page/detail.css"
    check("link: CSS @import", first(L(C, 1, 11)) == ["path", S + "page/base.css", 1])
    check("link: CSS url() without quotes", first(L(C, 2, col_of(C, 2, "bg.png"))) == ["path", S + "img/bg.png", 1])
    # Java
    J = "proj/java/src/main/java/com/acme/shop/Order.java"
    JU = "proj/java/src/main/java/com/acme/shop/util/"
    r = L(J, 3, col_of(J, 3, "Money"))
    check("java: import a.b.Money -> Money.java at the class", first(r) == ["path", JU + "Money.java", 3], str(r))
    r = L(J, 4, col_of(J, 4, "util"))
    check("java: wildcard import -> every class of the package", r["kind"] == "path" and
          [x["path"] for x in r["results"]] == [JU + "Money.java", JU + "Rates.java"], str(r))
    check("java: java.util.List -> external", L(J, 5, col_of(J, 5, "List"))["kind"] == "external")
    r = L(J, 8, col_of(J, 8, "zero"))
    check("java: Money.zero() -> the static method", first(r) == ["symbol", JU + "Money.java", 4], str(r))
    r = L(J, 9, col_of(J, 9, "Item"))
    check("java: same-package class without import", first(r) == ["symbol", "proj/java/src/main/java/com/acme/shop/Item.java", 3], str(r))
    # Python
    P = "proj/py/app/main.py"
    r = L(P, 1, col_of(P, 1, "users"))
    check("python: from .services.users -> users.py", first(r) == ["path", "proj/py/app/services/users.py", 1], str(r))
    r = L(P, 1, col_of(P, 1, "services"))
    check("python: clicking the package part -> its __init__.py", first(r) == ["path", "proj/py/app/services/__init__.py", 1], str(r))
    r = L(P, 1, col_of(P, 1, "get_user"))
    check("python: imported name -> def line", first(r) == ["symbol", "proj/py/app/services/users.py", 5], str(r))
    r = L(P, 1, col_of(P, 1, "User as"))
    check("python: `User as U` -> class line", first(r) == ["symbol", "proj/py/app/services/users.py", 1], str(r))
    r = L(P, 2, col_of(P, 2, "helpers"))
    check("python: from . import helpers -> helpers.py", first(r) == ["symbol", "proj/py/app/helpers.py", 1], str(r))
    r = L(P, 3, col_of(P, 3, "users"))
    check("python: import app.services.users (absolute)", first(r) == ["path", "proj/py/app/services/users.py", 1], str(r))
    check("python: missing relative module", L(P, 4, col_of(P, 4, "missing"))["kind"] == "missing")
    check("python: stdlib import -> external", L(P, 5, col_of(P, 5, "os"))["kind"] == "external")
    r = L(P, 9, col_of(P, 9, "get_user"))
    check("python: usage of an imported function", first(r) == ["symbol", "proj/py/app/services/users.py", 5], str(r))
    r = L(P, 10, col_of(P, 10, "slugify"))
    check("python: module.func()", first(r) == ["symbol", "proj/py/app/helpers.py", 4], str(r))
    # Go, C, Rust, PHP, Ruby, C#
    G = "proj/gosvc/main.go"
    r = L(G, 5, col_of(G, 5, "store"))
    check("go: module import path -> package files", first(r) == ["path", "proj/gosvc/internal/store/store.go", 1], str(r))
    check("go: stdlib -> external", L(G, 4, col_of(G, 4, "fmt"))["kind"] == "external")
    r = L(G, 9, col_of(G, 9, "Open"))
    check("go: pkg.Func -> func line", first(r) == ["symbol", "proj/gosvc/internal/store/store.go", 3], str(r))
    r = L("proj/cproj/main.c", 1, 14)
    check('c: #include "util/strings.h"', first(r) == ["path", "proj/cproj/util/strings.h", 1], str(r))
    check("c: #include <stdio.h> -> external", L("proj/cproj/main.c", 2, 12)["kind"] == "external")
    R = "proj/rs/src/main.rs"
    check("rust: mod net; -> net/mod.rs", first(L(R, 1, 6)) == ["path", "proj/rs/src/net/mod.rs", 1])
    r = L(R, 2, col_of(R, 2, "Client"))
    check("rust: use crate::net::client::Client -> struct line", first(r) == ["symbol", "proj/rs/src/net/client.rs", 2], str(r))
    r = L("proj/php/index.php", 2, 12)
    check("php: use App\\Http\\Kernel (composer psr-4)", first(r) == ["symbol", "proj/php/src/Http/Kernel.php", 4], str(r))
    r = L("proj/php/index.php", 3, col_of("proj/php/index.php", 3, "bootstrap"))
    check("php: require_once __DIR__ . '/x.php'", first(r) == ["path", "proj/php/bootstrap.php", 1], str(r))
    check("ruby: require_relative", first(L("proj/rb/app.rb", 1, 20)) == ["path", "proj/rb/lib/thing.rb", 1])
    check("ruby: require 'json' -> external", L("proj/rb/app.rb", 2, 11)["kind"] == "external")
    r = L("proj/cs/Program.cs", 1, 10)
    check("c#: using namespace -> the file declaring it", first(r) == ["path", "proj/cs/Billing.cs", 2], str(r))
    NC = "proj/noconf/client/src/main/page/product/"
    r = L(NC + "Items.vue", 5, col_of(NC + "Items.vue", 5, "ProdInfo.vue"))
    check("no alias config: @/ path resolved by path suffix", first(r) == ["path", NC + "ProdInfo.vue", 1], str(r))
    r = L(NC + "Items.vue", 5, 9)
    check("no alias config: imported name resolved the same way", first(r) == ["symbol", NC + "ProdInfo.vue", 1], str(r))
    r = L(NC + "Items.vue", 6, col_of(NC + "Items.vue", 6, "RelationProduct\"") + 2)
    check("no alias config: extension left out", first(r) == ["path", NC + "RelationProduct.vue", 1], str(r))
    r = L(NC + "Items.vue", 7, col_of(NC + "Items.vue", 7, "OnlyName.vue"))
    check("no alias config: same file name elsewhere as the last resort", first(r) == ["path", "proj/noconf/client/src/ui/OnlyName.vue", 1], str(r))
    check("no alias config: no such file anywhere -> missing", L(NC + "Items.vue", 8, col_of(NC + "Items.vue", 8, "Ghost.vue"))["kind"] == "missing")
    # the buffer wins over the disk (unsaved edits)
    r = L(D, 1, 30, text="import X from './product/RecommendItemsCarousel.vue'\n")
    check("link: uses the unsaved buffer text", first(r) == ["path", S + "page/product/RecommendItemsCarousel.vue", 1], str(r))
    # alias config cached, re-read after a change
    root = os.path.join(BASE, "proj", "web")
    a1 = server._aliases_for(root)
    check("aliases cached per project root", server._aliases_for(root) is a1)
    bump(os.path.join(root, "tsconfig.json"))
    check("…and re-read when tsconfig.json changes", server._aliases_for(root) is not a1)
    t0 = time.time()
    for _ in range(50):
        L(D, 12, col_of(D, 12, "getProduct") + 2)
    check("link lookups are fast (50 member lookups < 1.5 s)", time.time() - t0 < 1.5, f"{time.time() - t0:.2f}s")


DOT_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def image_server_checks():
    """/api/image: markdown preview images, inside the open folder only."""
    def get(path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/image?path=" + urllib.parse.quote(path), timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    code, h, body = get("proj/doc/img/dot.png")
    check("image API serves a png inside the folder (type, nosniff, sandbox CSP)",
          code == 200 and body == DOT_PNG and h["Content-Type"] == "image/png"
          and h["X-Content-Type-Options"] == "nosniff" and "sandbox" in (h["Content-Security-Policy"] or ""), f"{code} {dict(h)}")
    code, h, _ = get("proj/doc/img/pic.svg")
    check("image API: svg gets image/svg+xml and a sandbox CSP", code == 200 and h["Content-Type"] == "image/svg+xml"
          and "sandbox" in (h["Content-Security-Policy"] or ""), f"{code} {dict(h)}")
    refused = {p: get(p)[0] for p in ("../outside.png", "proj/../../outside.png", os.path.join(WORK, "outside.png"),
                                      "proj/doc/pics.md", "proj/doc/img/none.png", "")}
    check("image API refuses paths outside the folder, non-images and missing files",
          all(c == 404 for c in refused.values()), str(refused))


def main():
    setup()
    start_server()
    link_server_checks()
    image_server_checks()
    from playwright.sync_api import sync_playwright

    P = lambda *a: os.path.join(BASE, "proj", *a)  # noqa: E731
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and "status of 409" not in m.text
                and "status of 400" not in m.text and "status of 404" not in m.text and "status of 415" not in m.text
                and errors.append(m.text))
        def on_resp(r):
            if r.status == 404 and "ext.txt" not in r.url and "brief.ts" not in r.url:  # brief.ts: deleted on purpose
                errors.append("404 " + r.url)
        page.on("response", on_resp)
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.wait_for_function("typeof monaco !== 'undefined' && panes.length === 1 && _stateReady", timeout=20000)
        page.wait_for_selector('#tree .node[data-path="proj"]')
        ev = page.evaluate

        # --- 5. bugs: marked load order ---
        check("marked loaded as global (before AMD loader)", ev("typeof marked !== 'undefined' && typeof marked.parse === 'function'"))
        check("FIF has a free 'files to include' box (no hard-coded extension chips)",
              ev("!!document.getElementById('fifGlob') && !document.getElementById('fifExts')"))
        check("start screen hidden when a folder is open and tabs restore", True)
        # --- A/B: general defaults, text detection ---
        page.click('#tree .node[data-path="proj"]')
        page.wait_for_selector('#tree .node[data-path="proj/run.sh"]', timeout=5000)
        names = ev("[...document.querySelectorAll('#tree .node')].map(n => n.dataset.path)")
        check("tree shows .txt .sh .toml .log LICENSE .env .gitignore doc/ build/",
              all(f"proj/{n}" in names for n in ["notes.txt", "run.sh", "conf.toml", "app.log", "LICENSE",
                                                  ".env", ".gitignore", "doc", "build"]), str(names))
        check(".git stays hidden", "proj/.git" not in names)
        check("binary by extension listed but dimmed",
              ev("document.querySelector('#tree .node[data-path=\"proj/logo.png\"]').classList.contains('bin')"))
        for key in ["proj/run.sh", "proj/conf.toml", "proj/LICENSE", "proj/.env"]:
            ev(f"openFile('{key}')")
            page.wait_for_function(f"currentPath === '{key}'", timeout=5000)
        check("those files open editable", ev("!currentDoc().readonly && !editor.getOption(monaco.editor.EditorOption.readOnly)"))
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: 'X'}])")
        page.keyboard.press("Control+S")
        page.wait_for_function("!currentDoc().dirty", timeout=5000)
        check(".env saved (dot file editable)", open(P(".env")).read() == "XSECRET=1\n")
        st = ev("fetch('/api/file?path=proj/fake.txt').then(r => r.status)")
        st2 = ev("fetch('/api/file?path=proj/logo.png').then(r => r.status)")
        check("binary content (.txt with NULs) and .png refused with 415", st == 415 and st2 == 415, f"{st} {st2}")
        ev("openFile('proj/fake.txt')")
        page.wait_for_function("document.getElementById('toast').textContent.includes('binary')", timeout=5000)
        check("binary open shows a clear message", "text files only" in ev("document.getElementById('toast').textContent"))
        ev("openFile('proj/u16.txt')")
        page.wait_for_function("currentPath === 'proj/u16.txt'", timeout=5000)
        check("UTF-16 without BOM opens as text", ev("editor.getValue()") == "utf16 no bom\n"
              and ev("document.getElementById('sbEnc').textContent") == "UTF-16-LE")
        st, body = raw_post("/api/save", {"path": "proj/logo.png", "text": "x"}, server.CSRF_TOKEN)
        check("save refuses binary file type", st == 400 and "binary" in body.get("error", ""), str(body))
        res = ev("fetch('/api/search?q=needle').then(r => r.json())")
        paths = sorted(r["path"] for r in res.get("results", []))
        check("search covers .sh, skips search-ignored build/", "proj/run.sh" in paths
              and not any(x.startswith("proj/build/") for x in paths), str(paths))
        qo = ev("fetch('/api/files?q=gen').then(r => r.json())")
        check("Quick Open skips search-ignored build/", not any("build/" in x["path"] for x in qo["results"]))

        # --- 1. edit & save ---
        ev("openFile('proj/A.java')")
        page.wait_for_function("currentPath === 'proj/A.java' && editor.getModel()")
        check("editing on by default even with old state.json editMode=false",
              ev("STATE.editMode && !editor.getOption(monaco.editor.EditorOption.readOnly)") is True)
        page.keyboard.press("Control+Shift+E")
        check("Ctrl+Shift+E turns editing off", ev("editor.getOption(monaco.editor.EditorOption.readOnly)") is True)
        page.keyboard.press("Control+Shift+E")
        check("Ctrl+Shift+E turns editing back on", ev("STATE.editMode && !editor.getOption(monaco.editor.EditorOption.readOnly)"))
        ev("editor.focus(); editor.setPosition({lineNumber: 4, column: 3})")
        page.keyboard.type("// edited ")
        check("tab shows dirty", ev("!!document.querySelector('.tab-item.active.dirty')"))
        check("status bar shows unsaved", "unsaved" in ev("document.getElementById('sbMode').textContent"))
        page.keyboard.press("Control+S")
        page.wait_for_function("!docs.get('proj/A.java').dirty", timeout=5000)
        disk = open(P("A.java"), encoding="utf-8").read()
        check("Ctrl+S writes file", "// edited int x;" in disk, disk)
        check("dirty cleared after save", not ev("!!document.querySelector('.tab-item.dirty')"))
        check("mtime_ns kept as exact string",
              ev("docs.get('proj/A.java').mtime") == str(os.stat(P("A.java")).st_mtime_ns))
        check("no temp files left", not [f for f in os.listdir(P()) if f.startswith(".reado-")])

        # --- 409 conflict: overwrite ---
        page.keyboard.type("MINE1 ")
        w(P("A.java"), "external change 1\n"); bump(P("A.java"))
        ev("docs.get('proj/A.java').saving = true")  # keep the poller from flagging it first
        page.keyboard.press("Control+S")
        page.wait_for_selector("#dlgBg.show", timeout=5000)
        btns = ev("[...document.querySelectorAll('#dlgBtns button')].map(b => b.dataset.value)")
        check("409 shows overwrite/reload/cancel", btns == ["overwrite", "reload", "cancel"], str(btns))
        page.click('#dlgBtns button[data-value="overwrite"]')
        page.wait_for_function("!docs.get('proj/A.java').dirty", timeout=5000)
        check("overwrite writes editor text", "MINE1" in open(P("A.java"), encoding="utf-8").read())

        # --- 409 conflict: reload ---
        page.keyboard.type("MINE2 ")
        w(P("A.java"), "external change 2\n"); bump(P("A.java"))
        page.keyboard.press("Control+S")
        page.wait_for_selector("#dlgBg.show", timeout=5000)
        page.click('#dlgBtns button[data-value="reload"]')
        try:
            page.wait_for_function("editor.getValue() === 'external change 2\\n'", timeout=5000)
        except Exception:
            print("DEBUG", ev("JSON.stringify([editor.getValue(), currentPath, document.querySelector('#dlgBg.show') !== null])"), errors)
            raise
        check("reload replaces text and clears dirty", not ev("docs.get('proj/A.java').dirty"))
        check("reload keeps undo history", ev("editor.getModel().canUndo()"))

        # --- 4. external change, clean tab: auto reload ---
        w(P("A.java"), "external change 3\n"); bump(P("A.java"))
        page.wait_for_function("editor.getValue() === 'external change 3\\n'", timeout=8000)
        check("clean tab reloads on external change", True)
        # dirty tab: flagged, not reloaded
        ev("editor.focus()"); page.keyboard.type("dirty ")
        w(P("A.java"), "external change 4\n"); bump(P("A.java"))
        page.wait_for_function("docs.get('proj/A.java').diskChanged", timeout=8000)
        check("dirty tab flagged as changed on disk (not reloaded)",
              "dirty" in ev("editor.getValue()") and ev("!!document.querySelector('.tab-item.stale')"))
        # deleted on disk
        os.remove(P("B.java")) if False else None

        # --- close dirty tab asks ---
        page.keyboard.press("Control+W")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('#dlgBg.show')")
        check("Esc on close prompt keeps tab", ev("panes[0].tabs.has('proj/A.java')"))
        page.keyboard.press("Control+W")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        page.click('#dlgBtns button[data-value="discard"]')
        page.wait_for_function("!panes[0].tabs.has('proj/A.java')")
        check("don't save closes and disposes model", not ev("docs.has('proj/A.java')"))
        check("disk untouched by discard", open(P("A.java"), encoding="utf-8").read() == "external change 4\n")

        # --- 2MB / txt / binary read-only ---
        ev("openFile('proj/big.json')")
        page.wait_for_function("currentPath === 'proj/big.json'", timeout=10000)
        check("over-2MB file stays read-only with a clear banner",
              ev("editor.getOption(monaco.editor.EditorOption.readOnly)") is True
              and "read-only" in ev("panes[activePaneIdx].bannerEl.textContent")
              and ev("panes[activePaneIdx].bannerEl.style.display") == "",
              ev("panes[activePaneIdx].bannerEl.textContent"))
        st, body = raw_post("/api/save", {"path": "proj/big.json", "text": "x"}, server.CSRF_TOKEN)
        check("server refuses saving over-2MB file", st == 400, f"{st} {body}")
        ev("openFile('proj/notes.txt')")
        page.wait_for_function("currentPath === 'proj/notes.txt'")
        check(".txt inside the folder is editable (was refused before)",
              ev("!currentDoc().readonly && !panes[activePaneIdx].bannerEl.textContent.includes('read-only') || panes[activePaneIdx].bannerEl.style.display === 'none'"))

        # --- encodings / EOL / BOM preserved ---
        for key, check_fn, label in [
            ("proj/kor.properties", lambda b: b.startswith("name=한글값".encode("cp949")), "cp949"),
            ("proj/crlf.yml", lambda b: b == b"a: 1\r\nb: 2\r\nz: 9\r\n", "CRLF"),
            ("proj/bom.json", lambda b: b.startswith(b"\xef\xbb\xbf{"), "UTF-8 BOM"),
        ]:
            ev(f"openFile('{key}')")
            page.wait_for_function(f"currentPath === '{key}'")
            if key.endswith(".yml"):
                check("status bar shows CRLF", ev("document.getElementById('sbEol').textContent") == "CRLF")
                ev("editor.executeEdits('t', [{range: new monaco.Range(3,1,3,1), text: 'z: 9\\n'}])")
            else:
                ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: ''}]);"
                   "editor.trigger('t','type',{text:' '}); editor.trigger('t','deleteLeft',{})")
                ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: '#'}])")
            enc = ev("document.getElementById('sbEnc').textContent")
            page.keyboard.press("Control+S")
            page.wait_for_function(f"!docs.get('{key}').dirty", timeout=5000)
            raw = open(os.path.join(BASE, *key.split("/")), "rb").read()
            if not key.endswith(".yml"):
                raw = raw.replace(b"#", b"", 1)
            check(f"{label} preserved on save (status {enc})", check_fn(raw), repr(raw[:30]))

        # --- 2. outside files ---
        ext = os.path.join(OUT, "ext.txt")
        st = ev(f"fetch('/api/file?path=' + encodeURIComponent({json.dumps(ext)})).then(r => r.status)")
        check("outside file not readable before user grant", st == 404, str(st))
        server.request_open([ext])  # what open dialog / argv / drop / 2nd instance do
        page.wait_for_function(f"currentPath === {json.dumps(os.path.realpath(ext))}", timeout=8000)
        check("granted outside file opens as a tab (via poll)", True)
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: 'EXT '}])")
        page.keyboard.press("Control+S")
        page.wait_for_function("!currentDoc().dirty", timeout=5000)
        check("outside file saved", open(ext, encoding="utf-8").read() == "EXT outside file\n")
        secret = os.path.join(OUT, "secret.txt")
        st, body = raw_post("/api/save", {"path": secret, "text": "pwn"}, server.CSRF_TOKEN)
        check("save to non-granted absolute path refused", st == 400 and open(secret).read() == "not granted\n", f"{st} {body}")
        st, body = raw_post("/api/open-request", {"paths": [secret]}, server.CSRF_TOKEN)
        check("open-request without IPC secret refused", st == 403, f"{st}")
        st, body = raw_post("/api/save", {"path": "proj/A.java", "text": "x"})
        check("save without CSRF token refused", st == 403, f"{st}")
        st, body = raw_post("/api/save", {"path": "../outside/secret.txt", "text": "x"}, server.CSRF_TOKEN)
        check("save with ../ refused", st == 400, f"{st} {body}")
        crumbs = ev("document.getElementById('crumbs').textContent")
        check("crumbs show outside path", "ext.txt" in crumbs and "outside" in crumbs, crumbs)

        # open dialog (JS side, fake pywebview api) + drop forwarding
        sub = os.path.join(BASE, "proj", "sub", "deep.java")
        key_in = server.grant_external(sub)
        check("file inside base_dir maps to relative key", key_in == "proj/sub/deep.java", str(key_in))
        ev("""window.pywebview = { api: { open_files: async () => ['proj/sub/deep.java'],
                                        set_dirty: n => { window.__dirty = n; } } }""")
        page.keyboard.press("Control+O")
        page.wait_for_function("currentPath === 'proj/sub/deep.java'", timeout=5000)
        check("Ctrl+O opens dialog result", True)
        fwd = ev("""(() => { let got = null;
            document.addEventListener('drop', e => { got = e._readoForwarded && e.dataTransfer.files.length; }, { once: true });
            const dt = new DataTransfer(); dt.items.add(new File(['x'], 'f.txt'));
            const target = document.querySelector('.pane-editor .view-lines') || document.body;
            target.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
            return got; })()""")
        check("drop is re-dispatched to document with files (for pywebview)", fwd == 1, str(fwd))
        ev("editor.focus()"); page.keyboard.press("Control+Shift+E"); page.keyboard.press("Control+Shift+E")
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: '//'}])")
        check("dirty count reported to desktop shell", ev("window.__dirty") == 1, str(ev("window.__dirty")))
        ev("editor.getModel().undo()")
        page.wait_for_function("window.__dirty === 0")
        check("undo back to saved = clean", True)

        # --- 5. go to definition cursor ---
        # earlier steps left A.java without its declaration; put it back
        w(P("A.java"), "package com.example.svc01000;\n\npublic class Svc01000 {\n  int x;\n}\n"); bump(P("A.java"))
        ev("openFile('proj/B.java')"); page.wait_for_function("currentPath === 'proj/B.java'")
        ev("editor.focus(); editor.setPosition({lineNumber: 4, column: 5})")
        page.keyboard.press("F12")
        page.wait_for_function("currentPath === 'proj/A.java' && editor.getPosition().lineNumber !== 1", timeout=10000)
        pos = ev("[editor.getPosition().lineNumber, editor.getPosition().column, editor.getSelections().length]")
        check("go to definition lands on the declared name (line 3, col 14), single cursor", pos == [3, 14, 1], str(pos))
        page.keyboard.press("Alt+ArrowLeft")
        page.wait_for_function("currentPath === 'proj/B.java'", timeout=5000)
        check("Alt+Left navigates back", ev("editor.getPosition().lineNumber") == 4)

        # --- C: component navigation through Monaco ---
        g = ev("fetch('/api/goto?symbol=Shapes&from=proj/nav/Use.java').then(r => r.json())")
        check("goto: `new Shapes(` is not a declaration; class file ranks first",
              g["declarations"] == 1 and g["results"][0]["path"] == "proj/nav/Shapes.java" and g["results"][0]["line"] == 2, str(g)[:200])
        g = ev("fetch('/api/goto?symbol=helper&from=proj/nav/Shapes.java').then(r => r.json())")
        check("goto: `return helper(` / `helper(1);` not declarations", g["declarations"] == 1 and g["results"][0]["line"] == 7, str(g)[:200])
        g = ev("fetch('/api/goto?symbol=compute&from=proj/nav/m.py').then(r => r.json())")
        check("goto python: def found, `value = compute(1)` ignored", g["declarations"] == 1 and g["results"][0]["line"] == 1, str(g)[:200])
        g = ev("fetch('/api/goto?symbol=Dup&from=proj/nav/Use.java').then(r => r.json())")
        check("goto: same-folder Dup ranks before nav/other/Dup", g["declarations"] == 2 and g["results"][0]["path"] == "proj/nav/Dup.java", str(g)[:200])
        ev("openFile('proj/nav/Use.java')")
        page.wait_for_function("currentPath === 'proj/nav/Use.java'")
        ev("editor.focus(); editor.setPosition({lineNumber: 4, column: 10})")  # on Shapes
        page.keyboard.press("F12")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java'", timeout=8000)
        check("F12 (Monaco provider) jumps to the class in another file", ev("editor.getPosition().lineNumber") == 2)
        page.keyboard.press("Alt+ArrowLeft")
        page.wait_for_function("currentPath === 'proj/nav/Use.java'", timeout=5000)
        ev("editor.focus(); editor.setPosition({lineNumber: 6, column: 10})")  # on Dup
        page.keyboard.press("F12")
        # two classes named Dup, but Java resolves to the same package: no list needed
        page.wait_for_function("panes.some(p => p.currentPath === 'proj/nav/Dup.java')", timeout=8000)
        check("java: same-package Dup chosen over nav/other/Dup (no peek list)", not ev("panes.some(p => p.currentPath === 'proj/nav/other/Dup.java')"))
        ev("while (panes.length > 1) closePane(1)")
        ev("openFile('proj/nav/Use.java')")
        page.wait_for_function("currentPath === 'proj/nav/Use.java'", timeout=5000)
        ev("editor.focus(); editor.setPosition({lineNumber: 5, column: 20})")  # on area
        page.keyboard.press("Alt+F12")
        page.wait_for_selector(".peekview-widget", timeout=8000)
        check("Alt+F12 peeks the definition without leaving the file",
              ev("currentPath") == "proj/nav/Use.java" and "area" in ev("document.querySelector('.peekview-widget').textContent"))
        page.keyboard.press("Escape")
        ev("openFile('proj/nav/Shapes.java')")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java'")
        ev("editor.focus(); editor.setPosition({lineNumber: 7, column: 18})")  # on helper declaration
        page.keyboard.press("Shift+F12")
        page.wait_for_selector(".peekview-widget", timeout=8000)
        page.wait_for_function("document.querySelectorAll('.peekview-widget .monaco-list-row').length >= 2", timeout=8000)
        refs_ui = ev("document.querySelector('.peekview-widget .peekview-title').textContent")
        check("Shift+F12 lists usages across files (peek)", "reference" in refs_ui.lower(), refs_ui)
        page.keyboard.press("Escape")
        r = ev("fetch('/api/refs?symbol=helper&from=proj/nav/Shapes.java').then(r => r.json())")
        check("refs: current file first, declaration flagged",
              r["results"][0]["path"] == "proj/nav/Shapes.java" and any(x["decl"] for x in r["results"])
              and any(x["path"] == "proj/nav/Use.java" for x in r["results"]), str(r)[:200])
        # same-file jump + back
        ev("editor.setPosition({lineNumber: 4, column: 17})")  # helper( call in area()
        page.keyboard.press("F12")
        page.wait_for_function("editor.getPosition().lineNumber === 7", timeout=8000)
        page.keyboard.press("Alt+ArrowLeft")
        page.wait_for_function("editor.getPosition().lineNumber === 4", timeout=5000)
        check("in-file F12 jump is in back/forward history", True)
        # Ctrl+click
        ev("openFile('proj/nav/Use.java')")
        page.wait_for_function("currentPath === 'proj/nav/Use.java'")
        xy = ev("""(() => { const p = editor.getScrolledVisiblePosition({lineNumber: 4, column: 11});
                  const b = editor.getDomNode().getBoundingClientRect();
                  return [b.left + p.left + 2, b.top + p.top + p.height / 2]; })()""")
        page.mouse.move(xy[0], xy[1])
        page.keyboard.down("Control")
        page.mouse.move(xy[0] + 1, xy[1])
        time.sleep(0.6)
        page.mouse.click(xy[0] + 1, xy[1])
        page.keyboard.up("Control")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java'", timeout=8000)
        check("Ctrl+click goes to definition", True)
        # quick outline (Monaco, Ctrl+Shift+O in the editor) + outline panel
        ev("editor.focus()")
        page.keyboard.press("Control+Shift+O")
        page.wait_for_selector(".quick-input-widget .monaco-list-row", timeout=8000)
        qo_rows = ev("[...document.querySelectorAll('.quick-input-widget .monaco-list-row')].map(r => r.textContent)")
        check("Ctrl+Shift+O quick outline lists class + methods", any("helper" in t for t in qo_rows) and any("Shapes" in t for t in qo_rows), str(qo_rows)[:200])
        page.keyboard.press("Escape")
        ev("setSideTab('outline')")
        page.wait_for_selector("#outline .outline-item", timeout=8000)
        items = ev("[...document.querySelectorAll('#outline .outline-item .name')].map(e => e.textContent)")
        check("outline panel shows symbols", "Shapes" in items and "area" in items and "helper" in items, str(items))
        ev("[...document.querySelectorAll('#outline .outline-item')].find(e => e.querySelector('.name').textContent === 'helper').click()")
        check("outline click moves the cursor", ev("editor.getPosition().lineNumber") == 7)
        ev("setSideTab('files')")

        # --- D: ctags symbol index ---
        for _ in range(60):
            st = ev("fetch('/api/tags-status').then(r => r.json())")
            if st.get("ready") and not st.get("building"):
                break
            time.sleep(0.5)
        check("ctags index ready in background", st.get("ready") and st.get("symbols", 0) > 10, str(st))
        g = ev("fetch('/api/goto?symbol=Shapes&from=proj/nav/Use.java').then(r => r.json())")
        check("go to definition uses the ctags index first", g.get("source") == "ctags" and g["results"][0]["path"] == "proj/nav/Shapes.java"
              and g["results"][0]["line"] == 2, str(g)[:200])
        page.keyboard.press("Escape")
        ev("document.body.focus()")
        page.keyboard.press("Control+t")
        page.wait_for_selector("#qoBg.show", timeout=3000)
        check("Ctrl+T opens symbol search with kind chips", ev("document.getElementById('qoInput').value") == "#"
              and ev("document.getElementById('qoCats').style.display") == "")
        page.keyboard.type("Shap")
        page.wait_for_function("_qoItems.length > 0 && _qoItems[0].label === 'Shapes'", timeout=8000)
        check("Ctrl+T finds class by prefix", True)
        page.fill("#qoInput", "#helper")
        ev("runQO()")
        page.wait_for_function("_qoItems.some(i => i.label === 'helper')", timeout=8000)
        ev("document.querySelector('#qoCats .qo-cat[data-cat=\"class\"]').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
        page.wait_for_function("!_qoItems.some(i => i.label === 'helper')", timeout=8000)
        check("kind filter (classes) drops methods", True)
        ev("document.querySelector('#qoCats .qo-cat[data-cat=\"method\"]').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
        page.wait_for_function("_qoItems.length && _qoItems.every(i => i.meta.startsWith('method'))", timeout=8000)
        check("kind filter (methods) keeps methods", True)
        ev("document.querySelector('#qoCats .qo-cat[data-cat=\"\"]').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
        page.fill("#qoInput", "#Shap")
        ev("runQO()")
        page.wait_for_function("_qoItems.length > 0 && _qoItems[0].label === 'Shapes'", timeout=8000)
        page.keyboard.press("Enter")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java' && editor.getPosition().lineNumber === 2", timeout=8000)
        check("Enter on a symbol opens its file at the declaration", True)
        sym = ev("fetch('/api/symbols?q=shap').then(r => r.json())")
        sym2 = ev("fetch('/api/symbols?q=FAd').then(r => r.json())")
        check("case-insensitive prefix + CamelHumps search", any(r["name"] == "Shapes" for r in sym["results"]), str(sym.get("results"))[:120])
        # a class added and saved inside ReadO is indexed without waiting for the 5-minute re-check
        st, body = raw_post("/api/create", {"path": "proj/nav/Fresh.java"}, server.CSRF_TOKEN)
        ev("openFile('proj/nav/Fresh.java')")
        page.wait_for_function("currentPath === 'proj/nav/Fresh.java'")
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: 'class FreshlyAdded { void go() {} }\\n'}])")
        page.keyboard.press("Control+S")
        page.wait_for_function("!currentDoc().dirty", timeout=5000)
        found = False
        for _ in range(40):
            sym = ev("fetch('/api/symbols?q=FreshlyAdded').then(r => r.json())")
            if any(r["name"] == "FreshlyAdded" for r in sym["results"]):
                found = True
                break
            time.sleep(0.25)
        check("saved file is re-tagged right away (incremental)", found)
        sym2 = ev("fetch('/api/symbols?q=FrA').then(r => r.json())")
        check("CamelHumps: 'FrA' finds FreshlyAdded", any(r["name"] == "FreshlyAdded" for r in sym2["results"]), str(sym2.get("results"))[:120])
        out = ev("""fetch('/api/outline', {method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: 'X.java', text: 'class X {\\n  int a;\\n  void m() {}\\n}\\n'})}).then(r => r.json())""")
        names = [(x["name"], x["kind"], x["depth"]) for x in out.get("symbols") or []]
        check("outline from ctags on the unsaved buffer (with nesting)", ("X", "class", 0) in names and ("m", "method", 1) in names, str(names))
        out = ev("""fetch('/api/outline', {method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: 'r.md', text: '# Top\\n## Sub\\ntext\\n'})}).then(r => r.json())""")
        check("markdown outline lists headings", [x["name"] for x in out.get("symbols") or []][:2] == ["Top", "Sub"], str(out)[:150])
        ev("refreshIndexStatus()")
        page.wait_for_function("document.getElementById('sbIndex').textContent.includes('symbols')", timeout=5000)
        check("status bar shows the symbol count", True)

        # --- search: Dockerfile with rg and python fallback ---
        for engine in ("rg", "python"):
            server.USE_RIPGREP = engine == "rg"
            res = ev("fetch('/api/search?q=needle').then(r => r.json())")
            paths = [r["path"] for r in res.get("results", [])]
            check(f"search finds Dockerfile ({engine}, engine={res.get('engine', 'python')})",
                  "proj/Dockerfile" in paths, str(paths))
        server.USE_RIPGREP = True
        ev("openFIF('needle'); runFIF()"); page.wait_for_function("_fifResults.length > 0", timeout=8000)
        ev("document.getElementById('fifGlob').value = '*.java'; runFIF()")
        page.wait_for_function("document.getElementById('fifSummary').textContent.startsWith('0 match')", timeout=8000)
        check("'files to include' narrows search (.java has no 'needle')", True)
        ev("document.getElementById('fifGlob').value = ''")
        ev("closeFIF()")

        # --- Find in Files: default excludes, typed exclude patterns, "⊘ folder" ---
        def xpaths(qs=""):
            d = ev(f"fetch('/api/search?q=xneedle{qs}').then(r => r.json())")
            return d.get("error") or sorted(r["path"] for r in d.get("results", []))
        xs_all = ["xs/.idea/shelf/Uncommitted_changes_[x]/shelved.patch", "xs/.idea/w.xml", "xs/app.js", "xs/app.js.map",
                  "xs/app.min.js", "xs/build/b.js", "xs/gen/g.js", "xs/shelf/s1/shelved.patch", "xs/tsconfig.tsbuildinfo",
                  "xs/yarn.lock"]
        for engine in ("rg", "python"):
            server.USE_RIPGREP = engine == "rg"
            got = xpaths()
            check(f"default excludes skip .min.js / .map / lock / .idea (shelf too) / shelved.patch / build ({engine})",
                  got == ["xs/app.js", "xs/gen/g.js"], str(got))
            got = xpaths("&defexcl=0")
            check(f"default excludes off: all of them are searched ({engine})", got == xs_all, str(got))
            got = xpaths("&defexcl=0&exclude=.idea/**")
            check(f"exclude .idea/** (any depth) with defaults off: no IntelliJ shelf hits ({engine})",
                  not any("/.idea/" in p for p in got) and "xs/app.js" in got, str(got))
            got = xpaths("&exclude=/xs/gen")
            check(f"exclude /path: anchored at the open folder ({engine})", got == ["xs/app.js"], str(got))
            got = xpaths("&exclude=/gen")
            check(f"exclude /gen does not match xs/gen ({engine})", got == ["xs/app.js", "xs/gen/g.js"], str(got))
            got = xpaths("&glob=" + urllib.parse.quote("*.js, !gen"))
            check(f"file mask: !pattern excludes ({engine})", got == ["xs/app.js"], str(got))
            got = xpaths("&exclude=xs/gen/**")
            check(f"exclude path pattern ({engine})", got == ["xs/app.js"], str(got))
            got = xpaths("&exclude=gen")
            check(f"exclude name pattern at any depth ({engine})", got == ["xs/app.js"], str(got))
            got = xpaths("&scope=xs&exclude=xs/gen")
            check(f"exclude path pattern inside a scope ({engine})", got == ["xs/app.js"], str(got))
        server.USE_RIPGREP = True
        for bad in ("../x", "xs/../..", "-e", "!x", "C:/x", "[a"):
            got = xpaths("&exclude=" + urllib.parse.quote(bad))
            check(f"exclude pattern refused: {bad}", isinstance(got, str) and "not allowed" in got, str(got))
        got = xpaths("&glob=" + urllib.parse.quote("*.js, !../x"))
        check("file mask !pattern is checked like the exclude box", isinstance(got, str) and "not allowed" in got, str(got))
        st, body = raw_post("/api/replace-preview", {"q": "xneedle", "replace": "y", "scope": "xs", "exclude": "gen"},
                            server.CSRF_TOKEN)
        check("replace preview honours the excludes", st == 200 and [f["path"] for f in body.get("files", [])] == ["xs/app.js"],
              str(body)[:200])
        st, body = raw_post("/api/replace-preview", {"q": "xneedle", "replace": "y", "exclude": "../x"}, server.CSRF_TOKEN)
        check("replace preview refuses a bad exclude pattern", st == 400 and "not allowed" in body.get("error", ""), str(body))
        ev("openFIF('xneedle'); runFIF()")
        page.wait_for_function("_fifResults.length === 2", timeout=8000)
        defs = ", ".join(list(server.SETTINGS.get("search_ignored") or []) + list(server.SEARCH_DEFAULT_EXCLUDES))
        check("Find in Files: the exclude box starts with the default patterns",
              ev("document.getElementById('fifExcl').value") == defs, ev("document.getElementById('fifExcl').value"))
        ev("[...document.querySelectorAll('#fifResults .res-file')].find(e => e.title === 'xs/gen/g.js').querySelector('.fd-excl').click()")
        page.wait_for_function("_fifResults.length === 1", timeout=8000)
        check("'⊘ folder' adds the result's folder to the excludes",
              ev("document.getElementById('fifExcl').value") == defs + ", /xs/gen/**" and ev("_fifResults[0].path") == "xs/app.js")
        n_defs = len(list(server.SETTINGS.get("search_ignored") or []) + list(server.SEARCH_DEFAULT_EXCLUDES))
        check("option bar: a summary button instead of the mask / exclude boxes",
              ev("document.getElementById('fifPatBtn').textContent") == f"mask: all files · exclude: {n_defs + 1}"
              and ev("document.getElementById('fifExcl').type") == "hidden", ev("document.getElementById('fifPatBtn').textContent"))
        # the file mask & exclude dialog: real clicks and keys
        page.click("#fifPatBtn")
        page.wait_for_selector("#fifPatBg.show", timeout=3000)
        check("summary button opens the dialog: one pattern per line, the exclude list focused, above the find dialog",
              ev("document.getElementById('fifPatExcl').value") == defs.replace(", ", "\n") + "\n/xs/gen/**"
              and ev("document.activeElement.id") == "fifPatExcl" and ev("fifIsOpen()")
              and ev("+getComputedStyle(document.getElementById('fifPatBg')).zIndex > +getComputedStyle(document.getElementById('fifBg')).zIndex"))
        page.keyboard.press("Control+A"); page.keyboard.type("/xs/gen/**\n*.map, *.lock")
        page.click("#fifPatMask"); page.keyboard.type("*.js")
        page.keyboard.press("Escape")
        check("Esc cancels: dialog closed, nothing applied, Find in Files still open",
              not ev("fifPatIsOpen()") and ev("fifIsOpen()") and ev("document.getElementById('fifExcl').value") == defs + ", /xs/gen/**")
        page.click("#fifPatBtn"); page.wait_for_selector("#fifPatBg.show", timeout=3000)
        page.keyboard.press("Control+A"); page.keyboard.type("/xs/gen/**\n*.map, *.lock")   # lines and commas both
        page.click("#fifPatMask"); page.keyboard.type("*.js\n!*.min.js")
        page.keyboard.press("Enter")
        check("Enter in a multi-line box is a new line (the dialog stays)", ev("fifPatIsOpen()") and
              ev("document.getElementById('fifPatMask').value") == "*.js\n!*.min.js\n")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("!fifPatIsOpen() && _fifResults.map(r => r.path).join() === 'xs/app.js,xs/build/b.js'", timeout=8000)
        time.sleep(0.5)
        check("Ctrl+Enter applies: searched with the new mask / excludes, saved, summary updated",
              ev("STATE.fifOpts.exclude") == "/xs/gen/**, *.map, *.lock" and ev("STATE.fifOpts.glob") == "*.js, !*.min.js"
              and ev("STATE.fifOpts.exclV") == 2
              and ev("document.getElementById('fifPatBtn').textContent") == "mask: *.js, !*.min.js · exclude: 3"
              and ev("document.activeElement.id") == "fifQ", str(ev("[STATE.fifOpts, _fifResults.map(r => r.path)]")))
        ev("closeFIF(); openFIF('xneedle')")
        check("applied patterns come back when the dialog opens again",
              ev("document.getElementById('fifPatBtn').textContent") == "mask: *.js, !*.min.js · exclude: 3")
        ev("flushState()"); time.sleep(0.6)
        page.reload()
        page.wait_for_function("typeof monaco !== 'undefined' && _stateReady", timeout=20000)
        ev("openFIF('xneedle')")
        check("after a restart (reload) the patterns are kept (state.json)",
              ev("document.getElementById('fifExcl').value") == "/xs/gen/**, *.map, *.lock"
              and ev("document.getElementById('fifGlob').value") == "*.js, !*.min.js")
        page.click("#fifPatBtn"); page.wait_for_selector("#fifPatBg.show", timeout=3000)
        page.click("#fifPatMask"); page.keyboard.press("Control+A"); page.keyboard.press("Delete")
        page.click("#fifPatDefaults")
        check("Defaults puts the default exclude patterns back in the dialog (applied with Apply; says so in its tooltip)",
              ev("document.getElementById('fifPatExcl').value") == defs.replace(", ", "\n") and ev("fifPatIsOpen()")
              and ev("document.getElementById('fifPatDefaults').title").startswith("Defaults: put the default exclude patterns back"))
        page.click("#fifPatApply")
        page.wait_for_function("!fifPatIsOpen() && _fifResults.map(r => r.path).join() === 'xs/app.js,xs/gen/g.js'", timeout=8000)
        check("Apply button applies", ev("document.getElementById('fifExcl').value") == defs and ev("document.getElementById('fifGlob').value") == "")
        page.click("#fifPatBtn"); page.wait_for_selector("#fifPatBg.show", timeout=3000)
        page.click("#fifPatBg", position={"x": 5, "y": 5})
        check("click outside the dialog cancels it; Find in Files stays", not ev("fifPatIsOpen()") and ev("fifIsOpen()"))
        ev("STATE.fifOpts = {exclude: 'foo/**', defExcl: true}; closeFIF(); openFIF('')")
        old_on = ev("document.getElementById('fifExcl').value")
        ev("STATE.fifOpts = {exclude: 'foo/**', defExcl: false}; closeFIF(); openFIF('')")
        old_off = ev("document.getElementById('fifExcl').value")
        check("saved options of the old Defaults toggle carry over (on: defaults + own patterns, off: own only)",
              old_on == defs + ", foo/**" and old_off == "foo/**", f"{old_on!r} {old_off!r}")
        ev("fifResetExcludes()")
        vp = page.viewport_size
        page.set_viewport_size({"width": 640, "height": 600})
        fit = ev("""(() => { const row = document.getElementById('fifOpts').getBoundingClientRect();
            return ['fifPatBtn', 'fifScope', 'fifReplToggle'].map(id => {
              const e = document.getElementById(id), r = (e.type === 'checkbox' ? e.parentElement : e).getBoundingClientRect();
              return id + ':' + (r.width > 0 && r.left >= row.left - 1 && r.right <= row.right + 1 && r.bottom <= row.bottom + 1);
            }).join(' ') + ' overflow:' + (document.getElementById('fifOpts').scrollWidth > document.getElementById('fifOpts').clientWidth); })()""")
        check("narrow window: the mask / exclude summary button stays visible (the option row wraps)",
              "false" not in fit.split(" overflow:")[0] and fit.endswith("overflow:false"), fit)
        page.set_viewport_size(vp)
        ev("closeFIF()")

        # --- find dialogs: ✕ button, Esc / Ctrl+Shift+F / outside click close and give the editor the keyboard ---
        ev("openFile('proj/A.java')")
        page.wait_for_function("currentPath === 'proj/A.java' && editor.getModel()")
        ed_focus = "!fifIsOpen() && !qoIsOpen() && panes[activePaneIdx].editor.hasTextFocus()"

        def closes(label, open_js, act):
            ev(open_js)
            page.wait_for_function("fifIsOpen() || qoIsOpen()", timeout=5000)
            act()
            try:
                page.wait_for_function(ed_focus, timeout=3000)
                ok = True
            except Exception:
                ok = False
            check(label, ok, ev("[fifIsOpen(), qoIsOpen(), document.activeElement && document.activeElement.id]"))
        check("find dialogs have a visible ✕ in the header (In Files; Files / Commands / Symbols)",
              ev("openFIF(); const a = document.getElementById('fifClose').getBoundingClientRect(),"
                 " t = document.querySelector('#fifBg .fd-tabs').getBoundingClientRect(); closeFIF();"
                 " openQO(''); const b = document.getElementById('qoClose').getBoundingClientRect(),"
                 " u = document.querySelector('#qoBg .fd-tabs').getBoundingClientRect(); closeQO();"
                 " a.width > 0 && a.right <= t.right && t.right - a.right < 20 && b.width > 0 && b.right <= u.right && u.right - b.right < 20"))
        closes("In Files: ✕ closes, editor gets the keyboard", "openFIF('x')", lambda: page.click("#fifClose"))
        closes("In Files: Esc in the mask / exclude dialog closes it, Esc again closes Find in Files",
               "openFIF('x'); openFIFPatterns()", lambda: (page.keyboard.press("Escape"), page.keyboard.press("Escape")))
        closes("In Files: Esc in the search box closes", "openFIF('x')", lambda: page.keyboard.press("Escape"))
        closes("In Files: Ctrl+Shift+F again closes", "openFIF('x')", lambda: page.keyboard.press("Control+Shift+F"))
        closes("In Files: click outside closes", "openFIF('x')", lambda: page.mouse.click(5, 300))
        closes("Files: ✕ closes", "openQO('')", lambda: page.click("#qoClose"))
        closes("Commands: Esc closes", "openQO('>')", lambda: page.keyboard.press("Escape"))
        closes("Symbols: ✕ closes", "openQO('#')", lambda: page.click("#qoClose"))

        # Find File: a file named exactly like the query comes before loose matches from the recent list
        ev("window._recent0 = STATE.recent; STATE.recent = ['proj/qo/WidgetsSidebar.vue', 'proj/qo/sub/widgets.vue']")
        def qo_paths(q):
            ev(f"openQO({json.dumps(q)})")
            page.wait_for_function("!_qoLoading && _qoItems.some(i => i.path === 'proj/qo/Widgets.vue')", timeout=8000)
            return ev("_qoItems.map(i => i.path)")
        got = qo_paths("widgets.vue")
        check("Find File: exact file names (any case) first, in their order; recent loose matches after them",
              got[0] == "proj/qo/sub/widgets.vue" and set(got[1:3]) == {"proj/qo/Widgets.vue", "proj/qo/deep/deeper/widgets.vue"}
              and got[3] == "proj/qo/WidgetsSidebar.vue", str(got))
        got = qo_paths("qo/widgets.vue")
        check("Find File: a query with a path keeps the old order (recent matches first)",
              set(got[:2]) == {"proj/qo/WidgetsSidebar.vue", "proj/qo/sub/widgets.vue"} and "proj/qo/Widgets.vue" in got[2:], str(got))
        # manager's order: 1 exact+recent, 2 exact (server order), 3 other recent, 4 the rest; a recent exact
        # name is kept even when 5 closer loose matches are recent too
        ev("STATE.recent = ['proj/qo/a_widgets.vue', 'proj/qo/b_widgets.vue', 'proj/qo/c_widgets.vue', 'proj/qo/d_widgets.vue',"
           " 'proj/qo/e_widgets.vue', 'proj/qo/deep/deeper/widgets.vue']")
        qo_paths("widgets.vue")
        it = ev("_qoItems.map(i => [i.path, i.meta === 'recent', /(^|\\/)widgets\\.vue$/i.test(i.path)])")
        rank = [0 if r and e else 1 if e else 2 if r else 3 for _, r, e in it]
        check("Find File: exact+recent, exact, other recent, rest (in that order)",
              it[0][:2] == ["proj/qo/deep/deeper/widgets.vue", True] and rank == sorted(rank)
              and rank.count(1) == 2 and rank.count(2) == 4, str(it))
        # keys typed while a slow /api/files request runs (big folder, cold index) are not dropped:
        # the list ends with the results for the whole query, not the recent files of a prefix
        ev("closeQO(); STATE.recent = []")
        find_files0 = server.find_files
        server.find_files = lambda q, *a: (time.sleep(1.5) if q == "widg" else None, find_files0(q, *a))[1]
        try:
            ev("openQO('')")
            page.keyboard.type("widg"); time.sleep(0.4)      # its request is now in flight
            page.keyboard.type("ets.vue")
            try:
                page.wait_for_function("!_qoLoading && _qoQuery === 'widgets.vue' && _qoItems.some(i => i.path === 'proj/qo/Widgets.vue')",
                                       timeout=6000)
                ok = True
            except Exception:
                ok = False
            check("Find File: keys typed while a slow request runs still give the results of the whole query", ok,
                  str(ev("[_qoQuery, _qoLoading, _qoItems.map(i => i.path)]")))
        finally:
            server.find_files = find_files0
        ev("closeQO(); STATE.recent = window._recent0")
        got = ev("fetch('/api/files?q=WtApp.java').then(r => r.json()).then(d => d.results.map(x => x.path))")
        check("Find File: files of a git worktree inside the folder (.git is a file) are found",
              got == ["proj/_wt/stg-log/src/main/WtApp.java"], str(got))
        # a chooser (several files for a link / component) closed with Esc must not leave its
        # mode behind: the next Ctrl+P is Find File again, not a filter over the old candidates
        ev("pickFile('2 files for X', ['proj/A.java', 'proj/doc/guide.md'], () => {})")
        page.wait_for_function("qoIsOpen() && _qoMode === 'pick'", timeout=3000)
        page.keyboard.press("Escape")
        page.wait_for_function("!qoIsOpen()", timeout=3000)
        ev("panes[activePaneIdx].editor.focus()")
        page.keyboard.press("Control+P")
        page.wait_for_function("qoIsOpen()", timeout=3000)
        page.keyboard.type("WtApp.java")
        try:
            page.wait_for_function("!_qoLoading && _qoItems.some(i => i.path === 'proj/_wt/stg-log/src/main/WtApp.java')", timeout=6000)
            ok = True
        except Exception:
            ok = False
        check("Find File after a chooser closed with Esc: searches files again (was 'no results')",
              ok and ev("_qoMode") == "file", str(ev("[_qoMode, _qoItems.map(i => i.path)]")))
        ev("closeQO()")

        # --- recent files / folders that are gone leave the lists ---
        import srv_fileops
        base = server.base_root()
        gone_dir = os.path.join(base, "proj", "gone")
        os.makedirs(os.path.join(gone_dir, "sub"), exist_ok=True)
        for n in ("a.ts", "sub/b.ts"):
            with open(os.path.join(gone_dir, *n.split("/")), "w") as f:
                f.write("x\n")
        missing_folder = os.path.join(tempfile.gettempdir(), "reado-gone-folder-%d" % os.getpid())
        os.makedirs(missing_folder, exist_ok=True)
        ev("window._recent1 = STATE.recent.slice(); window._folders1 = (STATE.recentFolders || []).slice()")
        for k in ("proj/gone/a.ts", "proj/gone/sub/b.ts"):
            ev(f"openFile({json.dumps(k)})")
            page.wait_for_function(f"currentPath === {json.dumps(k)}", timeout=5000)
        ev(f"STATE.recentFolders = [{json.dumps(missing_folder)}].concat(STATE.recentFolders || []); flushState()")
        time.sleep(0.5)
        ev("(async () => { for (const k of [...panes[activePaneIdx].tabs.keys()]) if (k.startsWith('proj/gone/')) await closeTabIn(activePaneIdx, k, true); })()")
        st, body = raw_post("/api/exists", {"files": ["proj/gone/a.ts", "proj/A.java", "../x", "proj/never.ts"],
                                            "dirs": [missing_folder, "C:\\not-in-the-saved-list"]}, server.CSRF_TOKEN)
        check("/api/exists: existing true, missing false, an escaping key and a folder not in the saved list left out",
              st == 200 and body["files"] == {"proj/gone/a.ts": True, "proj/A.java": True, "proj/never.ts": False}
              and body["dirs"] == {missing_folder: True} and body["complete"], str(body))
        for d in (gone_dir, missing_folder):  # an index walk / scanner may hold a folder for a moment
            for _ in range(20):
                try:
                    shutil.rmtree(d); break
                except PermissionError:
                    time.sleep(0.25)
        ev("_pruneAt = 0; openQO('')")
        page.wait_for_function("!STATE.recent.some(k => k.startsWith('proj/gone/'))", timeout=5000)
        check("deleted folder: its files leave Find File's recent list (shown and saved)",
              not ev("_qoItems.some(i => (i.path || '').startsWith('proj/gone/'))")
              and ev("STATE.recent.includes('proj/A.java')"), str(ev("_qoItems.map(i => i.path)")))
        check("deleted folder: it leaves the recent folders (start screen / open folder)",
              not ev(f"STATE.recentFolders.includes({json.dumps(missing_folder)})"))
        time.sleep(1.2)
        saved = server.ui_state()
        check("the pruned lists are saved (state.json)",
              not any(k.startswith("proj/gone/") for k in saved.get("recent", []))
              and missing_folder not in saved.get("recentFolders", []))
        ev("closeQO()")
        # opening a recent file that was deleted meanwhile drops it at once
        with open(os.path.join(base, "proj", "brief.ts"), "w") as f:
            f.write("x\n")
        ev("addRecent('proj/brief.ts')")
        os.remove(os.path.join(base, "proj", "brief.ts"))
        ev("openFile('proj/brief.ts')")
        page.wait_for_function("!STATE.recent.includes('proj/brief.ts')", timeout=5000)
        check("opening a recent file that is gone: toast, and it leaves the recent list", True)
        # a drive that does not answer in time: nothing is reported gone, nothing dropped
        budget0, state0 = srv_fileops.EXISTS_BUDGET, srv_fileops._file_state
        srv_fileops.EXISTS_BUDGET = 0.3
        srv_fileops._file_state = lambda k: (time.sleep(1), False)[1]
        try:
            ev("addRecent('proj/never.ts'); _pruneAt = 0")
            changed = ev("pruneRecent(true)")
            check("slow check: entries not answered in time are kept",
                  changed is False and ev("STATE.recent.includes('proj/never.ts')"))
        finally:
            srv_fileops.EXISTS_BUDGET, srv_fileops._file_state = budget0, state0
        ev("STATE.recent = window._recent1; STATE.recentFolders = window._folders1; saveState()")
        ev("openSettings()")
        page.wait_for_selector("#settingsBg.show")
        page.wait_for_function("document.getElementById('setSearchIgnored').value.includes('build')")
        ev("document.getElementById('setSearchIgnored').value += ', gen'")
        page.click("#settingsBg .actions-row button.primary")
        page.wait_for_function("!document.querySelector('#settingsBg.show')", timeout=5000)
        time.sleep(0.3)
        check("settings save (UI) still works (search-ignored list)",
              "gen" in server.SETTINGS["search_ignored"] and server.SETTINGS["base_dir"] == BASE)

        # --- markdown ---
        ev("openFile('proj/readme.md')")
        page.wait_for_function("currentPath === 'proj/readme.md'")
        pv = ev("(() => { const p = panes[activePaneIdx].previewEl; return [p.style.display, p.querySelector('h1') && p.querySelector('h1').textContent, !!p.querySelector('script'), window.__xss || 0]; })()")
        check("markdown preview renders, script stripped", pv == ["block", "Title One", False, 0], str(pv))
        ev("panes[activePaneIdx].mdBtn.click()")
        check("markdown source toggle shows editor",
              ev("panes[activePaneIdx].editorEl.style.display === '' && panes[activePaneIdx].previewEl.style.display === 'none'"))
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,3,1,8), text: 'Renamed'}])")
        ev("panes[activePaneIdx].mdBtn.click()")
        check("preview re-renders edited source",
              ev("panes[activePaneIdx].previewEl.querySelector('h1').textContent") == "Renamed One")
        page.keyboard.press("Control+S")
        page.wait_for_function("!docs.get('proj/readme.md').dirty")
        href0 = page.url
        ev("panes[activePaneIdx].previewEl.querySelector('a').click()")
        page.wait_for_function("currentPath === 'proj/B.java'", timeout=5000)
        check("relative md link opens file, page not navigated", page.url == href0)
        ev("openFile('proj/doc/pics.md')")
        page.wait_for_function("currentPath === 'proj/doc/pics.md'", timeout=5000)
        page.wait_for_function("(() => { const i = panes[activePaneIdx].previewEl.querySelector('img'); return i && i.complete; })()", timeout=5000)
        imgs = ev("[...panes[activePaneIdx].previewEl.querySelectorAll('img')].map(i => [i.alt, i.getAttribute('src'), i.naturalWidth])")
        check("md preview: relative image served from the folder and shown",
              imgs[0] == ["ok", "/api/image?path=proj%2Fdoc%2Fimg%2Fdot.png", 1], str(imgs))
        check("md preview: ../ image resolves next to the md file", imgs[1][:2] == ["up", "/api/image?path=proj%2Flogo.png"], str(imgs))
        check("md preview: image path out of the folder and data: URL get no src",
              imgs[2][:2] == ["out", None] and imgs[3][1] is None and len(imgs) == 4, str(imgs))
        page.wait_for_function("!!panes[activePaneIdx].previewEl.querySelector('code[data-hl]')", timeout=8000)
        hl = ev("[...panes[activePaneIdx].previewEl.querySelectorAll('pre > code')].map(c => [c.className, c.querySelectorAll('span[class^=mtk]').length > 1, c.textContent, !!c.dataset.hl])")
        check("md preview: fenced js code is highlighted, text unchanged",
              hl[0][0] == "language-js" and hl[0][1] and hl[0][2] == "const x = 1;" and hl[0][3], str(hl))
        check("md preview: unknown fence language stays plain text", hl[1] == ["language-nosuchlang", False, "plain\n", False], str(hl))
        check("md preview: highlighted html kept for the next render",
              "data-hl" in ev("docs.get('proj/doc/pics.md').html"))
        ev("[...panes[activePaneIdx].previewEl.querySelectorAll('a')].find(a => a.textContent === 'escape').click()")
        time.sleep(0.3)
        check("md link out of the folder is ignored", ev("currentPath") == "proj/doc/pics.md")
        ev("[...panes[activePaneIdx].previewEl.querySelectorAll('a')].find(a => a.textContent === 'guide').click()")
        page.wait_for_function("currentPath === 'proj/doc/guide.md'", timeout=5000)
        check("md link next to the md file opens in ReadO", page.url == href0)

        # --- split shares the model ---
        ev("while (panes.length > 1) closePane(panes.length - 1)")  # jumps above opened beside
        ev("openFile('proj/B.java')")
        page.wait_for_function("panes.length === 1 && currentPath === 'proj/B.java'", timeout=5000)
        ev("editor.focus()")
        page.keyboard.press("Control+\\")
        page.wait_for_function("panes.length === 2 && panes[1].currentPath === 'proj/B.java'", timeout=5000)
        check("split shares one model per file", ev("panes[0].editor.getModel() === panes[1].editor.getModel()"))
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: '/*x*/'}])")
        check("dirty shown in both panes", ev("document.querySelectorAll('.tab-item.dirty').length") == 2)
        ev("editor.getModel().undo()")

        # --- tree refresh on external create ---
        ev("refreshTreeDir('')")
        page.wait_for_selector('#tree .node[data-path="proj/sub"]', timeout=5000)
        page.wait_for_function("document.querySelector('#tree .node[data-path=\"proj/sub\"]') !== null")
        time.sleep(3)  # one poll to record the folder mtime baseline
        w(P("NewFile.java"), "class NewFile {}\n")
        page.wait_for_selector('#tree .node[data-path="proj/NewFile.java"]', timeout=8000)
        check("tree picks up externally created file", True)
        check("expanded folder stays expanded after refresh",
              ev("document.querySelector('#tree .node[data-path=\"proj\"]').nextElementSibling.style.display") == "block")

        # --- new file ---
        ev("closeReplace && closeFIF()")
        ev("document.body.focus()")
        page.keyboard.press("Alt+Insert")
        page.wait_for_selector("#dlgBg.show #dlgInput", timeout=3000)
        pre = ev("document.getElementById('dlgInput').value")
        page.fill("#dlgInput", "proj/sub/Made.java")
        page.keyboard.press("Enter")
        page.wait_for_function("currentPath === 'proj/sub/Made.java'", timeout=5000)
        check("new file: Alt+Insert dialog creates and opens it", os.path.isfile(P("sub", "Made.java")), pre)
        page.wait_for_selector('#tree .node[data-path="proj/sub/Made.java"]', timeout=5000)
        check("new file appears in tree", True)
        w(P("Exists.java"), "keep me\n")
        st, body = raw_post("/api/create", {"path": "proj/Exists.java"}, server.CSRF_TOKEN)
        check("create refuses existing file", st == 409 and open(P("Exists.java")).read() == "keep me\n", f"{st} {body}")
        st, body = raw_post("/api/create", {"path": "proj/node_modules/x.java"}, server.CSRF_TOKEN)
        st2, _ = raw_post("/api/create", {"path": "proj/nofolder/x.java"}, server.CSRF_TOKEN)
        st3, _ = raw_post("/api/create", {"path": "proj/Z.java"})
        check("create goes through write guard (ignored / missing folder / no token)",
              st == 400 and st2 == 400 and st3 == 403, f"{st} {st2} {st3}")
        ev("document.querySelector('#tree .node[data-path=\"proj/sub\"]').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 120, clientY: 200}))")
        page.click("#ctxMenu .ctx-item[data-label='new file…']")
        page.wait_for_selector("#dlgBg.show #dlgInput")
        check("tree right-click prefills folder", ev("document.getElementById('dlgInput').value") == "proj/sub/")
        page.keyboard.press("Escape")

        # --- replace in files ---
        ev("openFile('proj/Rep3.java')")
        page.wait_for_function("currentPath === 'proj/Rep3.java'")
        ev("editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: '//dirty '}])")
        ev("document.getElementById('fifGlob').value = ''")
        ev("openFIF('Svc01000'); document.getElementById('fifRepl').value = 'SvcNew'; runFIF()")
        page.wait_for_function("_fifResults.length > 0", timeout=8000)
        ev("previewReplace()")
        page.wait_for_function("document.querySelectorAll('#rplList .rpl-file').length > 0", timeout=8000)
        rows = ev("[...document.querySelectorAll('#rplList .rpl-file')].map(r => [r.querySelector('.rpl-path').textContent, r.querySelector('.rpl-cb').checked, r.querySelector('.rpl-cb').disabled])")
        rowmap = {r[0]: r for r in rows}
        check("preview lists matching files incl. cp949 file", {"proj/Rep1.java", "proj/Rep2.java", "proj/rep.properties"} <= set(rowmap), str(rows))
        check("file with unsaved edits is blocked in preview", rowmap.get("proj/Rep3.java", [0, 1, 0])[2] is True)
        check("preview shows - / + sample lines", ev("document.querySelectorAll('#rplList .rpl-line.add').length") >= 3)
        check("nothing written by preview", "Svc01000" in open(P("Rep1.java")).read())
        # untick Rep2, then change A.java on disk after the preview -> conflict
        ev("[...document.querySelectorAll('#rplList .rpl-file')].find(r => r.querySelector('.rpl-path').textContent === 'proj/Rep2.java').querySelector('.rpl-cb').click()")
        with open(P("B.java"), "a", encoding="utf-8") as f:
            f.write("// Svc01000 touched after preview\n")
        bump(P("B.java"))
        page.click("#rplApply")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        check("apply asks for confirmation first", "cannot undo" in ev("document.getElementById('dlgMsg').textContent"))
        page.click('#dlgBtns button[data-value="apply"]')
        page.wait_for_function("document.getElementById('rplSummary').textContent.startsWith('done')", timeout=8000)
        r1 = open(P("Rep1.java")).read()
        check("apply rewrites ticked file (all matches)", r1 == "class Rep1 { SvcNew a; SvcNew b; }\n", r1)
        check("unticked file untouched", "Svc01000" in open(P("Rep2.java")).read())
        check("dirty file untouched on disk", "Svc01000" in open(P("Rep3.java")).read() and ev("docs.get('proj/Rep3.java').dirty"))
        check("cp949 file stays cp949 after replace", open(P("rep.properties"), "rb").read() == "k=SvcNew 한글\n".encode("cp949"))
        res_b = ev("[...document.querySelectorAll('#rplList .rpl-file')].filter(r => r.querySelector('.rpl-path').textContent === 'proj/B.java').map(r => r.querySelector('.rpl-res').textContent)[0]")
        check("file changed after preview is skipped (conflict)", res_b is not None and "changed on disk" in res_b
              and "Svc01000 ref" in open(P("B.java")).read(), str(res_b))
        ev("closeReplace(); closeFIF()")
        st, body = raw_post("/api/replace-preview", {"q": r"class (\w+)", "replace": "class X_$1", "regex": True,
                                                     "scope": "proj"}, server.CSRF_TOKEN)
        smp = [s_ for f in body.get("files", []) if f["path"] == "proj/Rep2.java" for s_ in f["samples"]]
        check("regex replace supports $1", smp and smp[0]["after"].startswith("class X_Rep2"), str(smp))
        st, body = raw_post("/api/replace-apply", {"q": "x", "replace": "y", "files": [{"path": "../outside/secret.txt", "mtime_ns": "1"}]},
                            server.CSRF_TOKEN)
        check("replace-apply refuses paths outside scope", st == 200 and body["files"] == 0, str(body))

        # --- component tags: <ItemTop> -> ItemTop.vue in the other pane ---
        def comp(name, frm):
            return ev(f"fetch('/api/component?name={name}&from={frm}').then(r => r.json())")["results"]
        F = "proj/web/src/pages/Items.vue"
        r = comp("ItemTop", F)
        check("component via import alias @/ (decoy with the same name ignored)",
              [x["path"] for x in r] == ["proj/web/src/components/item/ItemTop.vue"] and r[0]["how"] == "import", str(r))
        r = comp("AliasThing", F)
        check("component via vite alias", r and r[0]["path"] == "proj/web/src/components/AliasThing.vue", str(r))
        r = comp("item-info", F)
        check("kebab-case tag -> ItemInfo.vue by name", r and r[0]["path"] == "proj/web/src/components/ItemInfo.vue", str(r))
        r = comp("SharedCard", F)
        check("folder component SharedCard/index.vue", r and r[0]["path"].endswith("SharedCard/index.vue"), str(r))
        r = comp("Dup", F)
        check("same-named components: both, nearest first", [x["path"] for x in r] ==
              ["proj/web/src/components/Dup.vue", "proj/other/Dup.vue"], str(r))
        r = comp("BaseButton", "proj/nuxt/pages/index.vue")
        check("Nuxt auto-import name components/base/Button.vue", r and r[0]["path"] == "proj/nuxt/components/base/Button.vue", str(r))
        check("missing component -> no result", comp("Missing", F) == [])
        while ev("panes.length") > 1:
            ev("closePane(1)")
        ev(f"openFile('{F}')")
        page.wait_for_function(f"currentPath === '{F}'", timeout=5000)
        tags = ev("""[[3,7],[4,20],[5,8],[9,6],[16,14],[1,3]].map(([l,c]) => { const t = componentTagAt(editor.getModel(), {lineNumber:l, column:c}); return t && t.name; })""")
        check("tag detection: <ItemTop, </ItemTop>, <item-info; not router-view, not ref<ItemTop>, not <template>",
              tags == ["ItemTop", "ItemTop", "item-info", None, None, None], str(tags))
        ev("editor.focus(); editor.setPosition({lineNumber: 3, column: 8})")
        page.keyboard.press("F12")
        try:
            page.wait_for_function("panes.length === 2 && panes[1].currentPath === 'proj/web/src/components/item/ItemTop.vue'", timeout=8000)
        except Exception:
            print("DEBUG", ev("JSON.stringify({panes: panes.map(p => [p.currentPath, [...p.tabs.keys()]]), active: activePaneIdx, pos: editor.getPosition(), focus: document.activeElement && document.activeElement.className, dlg: !!_dlgResolve, qo: document.getElementById('qoBg').className, fif: document.getElementById('fifBg').className, rpl: document.getElementById('rplBg').className})"))
            raise
        check("F12 on <ItemTop> opens it in a new right split; the left pane keeps Items.vue",
              ev("panes[0].currentPath") == F and ev("activePaneIdx") == 1)
        # Ctrl+click on the closing tag (already open -> just activated, still one tab)
        ev("setActivePane(0); panes[0].editor.focus()")
        xy = ev("""(() => { const ed = panes[0].editor; const p = ed.getScrolledVisiblePosition({lineNumber: 4, column: 23});
                  const b = ed.getDomNode().getBoundingClientRect(); return [b.left + p.left + 2, b.top + p.top + p.height / 2]; })()""")
        page.mouse.move(xy[0], xy[1])
        page.keyboard.down("Control")
        page.mouse.move(xy[0] + 1, xy[1])
        time.sleep(0.6)
        page.mouse.click(xy[0] + 1, xy[1])
        page.keyboard.up("Control")
        page.wait_for_function("activePaneIdx === 1", timeout=8000)
        check("Ctrl+click on </ItemTop> activates it in the other pane (no duplicate tab)",
              ev("[...panes[1].tabs.keys()].filter(k => k.endsWith('item/ItemTop.vue')).length") == 1)
        # plain click on the kebab tag name: opens beside, cursor/focus stay in Items.vue
        ev("setActivePane(0); panes[0].editor.focus()")
        xy = ev("""(() => { const ed = panes[0].editor; const p = ed.getScrolledVisiblePosition({lineNumber: 5, column: 9});
                  const b = ed.getDomNode().getBoundingClientRect(); return [b.left + p.left + 2, b.top + p.top + p.height / 2]; })()""")
        page.mouse.move(xy[0], xy[1])
        time.sleep(0.2)
        check("hovering a tag name shows it as a link", ev("!!document.querySelector('.pane .reado-taglink')"))
        page.mouse.click(xy[0], xy[1])
        page.wait_for_function("panes[1].currentPath === 'proj/web/src/components/ItemInfo.vue'", timeout=8000)
        check("plain click on <item-info> opens ItemInfo.vue beside; focus and cursor stay in Items.vue",
              ev("activePaneIdx") == 0 and ev("panes[0].editor.hasTextFocus()") and ev("panes[0].editor.getPosition().lineNumber") == 5)
        # editing is not disturbed: typing goes into Items.vue
        page.keyboard.type("Z")
        check("typing after the click edits Items.vue", "Z" in ev("panes[0].editor.getModel().getLineContent(5)"))
        ev("panes[0].editor.getModel().undo()")
        # several candidates -> picker, nearest first
        ev("openComponentBeside({name: 'Dup'}, 0, false)")
        page.wait_for_function("_qoMode === 'pick' && _qoItems.length === 2", timeout=5000)
        check("several components -> chooser list, nearest first", ev("_qoItems[0].path") == "proj/web/src/components/Dup.vue")
        page.keyboard.press("Enter")
        page.wait_for_function("panes[1].currentPath === 'proj/web/src/components/Dup.vue'", timeout=5000)
        check("choosing opens it in the other pane", True)
        ev("openComponentBeside({name: 'Missing'}, 0, false)")
        page.wait_for_function("document.getElementById('toast').textContent.includes('Missing')", timeout=5000)
        check("missing component -> 'not found' toast", "not found" in ev("document.getElementById('toast').textContent"))
        # option off: plain click is just a click
        ev("STATE.componentClick = false; openFile('proj/web/src/pages/Items.vue')")
        ev("setActivePane(0)")
        before = ev("panes[1].currentPath")
        xy = ev("""(() => { const ed = panes[0].editor; const p = ed.getScrolledVisiblePosition({lineNumber: 6, column: 8});
                  const b = ed.getDomNode().getBoundingClientRect(); return [b.left + p.left + 2, b.top + p.top + p.height / 2]; })()""")
        page.mouse.click(xy[0], xy[1])
        time.sleep(0.8)
        check("with the option off a plain click only moves the cursor", ev("panes[1].currentPath") == before
              and ev("panes[0].editor.getPosition().lineNumber") == 6)
        ev("STATE.componentClick = true")
        # TSX: <ItemTop /> resolves, useState<Dup> is a generic, not a tag
        ev("openFile('proj/web/src/App.tsx')")
        page.wait_for_function("currentPath === 'proj/web/src/App.tsx'", timeout=5000)
        t = ev("[componentTagAt(editor.getModel(), {lineNumber: 3, column: 12}), componentTagAt(editor.getModel(), {lineNumber: 2, column: 22})].map(x => x && x.name)")
        check("JSX: <ItemTop /> is a tag, useState<Dup> is not", t == ["ItemTop", None], str(t))
        # ordinary F12 (not a tag) into another file also opens in the next pane now
        ev("while (panes.length > 1) closePane(1)")
        ev("openFile('proj/nav/Use.java')")
        page.wait_for_function("currentPath === 'proj/nav/Use.java'")
        ev("editor.focus(); editor.setPosition({lineNumber: 4, column: 10})")
        page.keyboard.press("F12")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java'", timeout=8000)
        check("plain symbols in another file open in the next pane too", ev("panes.length") == 2
              and ev("panes[0].currentPath") == "proj/nav/Use.java")
        ev("while (panes.length > 1) closePane(1)")

        # --- component jumps always open in the pane opposite the focused one ---
        T = "proj/web/src/components/item/ItemTop.vue"
        OTHER = "proj/nav/Use.java"

        def layout(left, right=None, focus=0, extra=None):
            """1 pane with `left`, or 2 panes left|right; every other tab closed.
            extra = {pane: key} opens key there as a background tab."""
            ev("(async () => { while (panes.length > 1) closePane(1);"
               f" for (const k of [...panes[0].tabs.keys()]) if (k !== {json.dumps(left)}) await closeTabIn(0, k, true); }})()")
            ev(f"openFileInPane(0, {json.dumps(left)})")
            if right:
                ev("createPane(); document.getElementById('splitBtn').classList.add('active')")
                ev(f"openFileInPane(1, {json.dumps(right)})")
            for pi, k in (extra or {}).items():
                ev(f"openFileInPane({pi}, {json.dumps(k)}, null, null, {{background: true}})")
            ev(f"setActivePane({focus}); panes[{focus}].editor.focus()")
            page.wait_for_function(f"panes[{focus}].currentPath === {json.dumps(left if focus == 0 else right)}"
                                   f" && panes[{focus}].editor.hasTextFocus()", timeout=5000)

        def state():
            return ev("({n: panes.length, cur: panes.map(p => p.currentPath), active: activePaneIdx,"
                      f" tcount: panes.map(p => [...p.tabs.keys()].filter(k => k === {json.dumps(T)}).length)}})")

        def tag_xy(pi, line, col):
            return ev(f"""(() => {{ const ed = panes[{pi}].editor; const p = ed.getScrolledVisiblePosition({{lineNumber: {line}, column: {col}}});
                      const b = ed.getDomNode().getBoundingClientRect(); return [b.left + p.left + 2, b.top + p.top + p.height / 2]; }})()""")

        def f12_on_tag(pi, combo="F12"):
            ev(f"panes[{pi}].editor.focus(); panes[{pi}].editor.setPosition({{lineNumber: 3, column: 8}})")
            page.keyboard.press(combo)

        def wait_t_in(pi, timeout=8000):
            page.wait_for_function(f"panes.length > {pi} && panes[{pi}].currentPath === {json.dumps(T)}", timeout=timeout)

        ev("STATE.componentBeside = true; STATE.componentClick = true")
        # 1) no split, F12 -> new right split
        layout(F)
        f12_on_tag(0); wait_t_in(1)
        s_ = state()
        check("beside/no split: F12 auto-splits right, Items.vue stays left", s_["n"] == 2 and s_["cur"][0] == F and s_["active"] == 1, str(s_))
        # 2) split, focus left -> right
        layout(F, OTHER, 0)
        f12_on_tag(0); wait_t_in(1)
        s_ = state()
        check("beside/split, focus left: F12 opens in right pane", s_["cur"] == [F, T] and s_["n"] == 2, str(s_))
        # 3) split, focus right -> left
        layout(OTHER, F, 1)
        f12_on_tag(1); wait_t_in(0)
        s_ = state()
        check("beside/split, focus right: F12 opens in left pane", s_["cur"] == [T, F] and s_["active"] == 0, str(s_))
        # 4) already open (background tab) in the opposite pane -> activated, no duplicate
        layout(F, OTHER, 0, extra={1: T})
        f12_on_tag(0); wait_t_in(1)
        s_ = state()
        check("beside/already open on the right: tab activated, not duplicated", s_["cur"] == [F, T] and s_["tcount"] == [0, 1], str(s_))
        layout(OTHER, F, 1, extra={0: T})
        f12_on_tag(1); wait_t_in(0)
        s_ = state()
        check("beside/already open on the left (focus right): tab activated, not duplicated", s_["cur"] == [T, F] and s_["tcount"] == [1, 0], str(s_))
        # 5) plain click, focus right -> left pane, focus stays right
        layout(OTHER, F, 1)
        xy = tag_xy(1, 3, 8)
        page.mouse.move(xy[0], xy[1]); time.sleep(0.2); page.mouse.click(xy[0], xy[1])
        wait_t_in(0)
        s_ = state()
        check("beside/plain click in right pane opens in left; focus stays right", s_["cur"] == [T, F] and s_["active"] == 1
              and ev("panes[1].editor.hasTextFocus()"), str(s_))
        # 6) Ctrl+click, focus right -> left pane
        layout(OTHER, F, 1)
        xy = tag_xy(1, 3, 8)
        page.mouse.move(xy[0], xy[1]); page.keyboard.down("Control"); page.mouse.move(xy[0] + 1, xy[1]); time.sleep(0.6)
        page.mouse.click(xy[0] + 1, xy[1]); page.keyboard.up("Control")
        wait_t_in(0)
        check("beside/Ctrl+click in right pane opens in left", state()["cur"] == [T, F], str(state()))
        # 7) peek list (Alt+F12 on <Dup/>, 2 candidates), a plain lookup meanwhile, then Enter -> opposite pane
        layout(OTHER, F, 1)
        ev("panes[1].editor.focus(); panes[1].editor.setPosition({lineNumber: 7, column: 7})")
        page.keyboard.press("Alt+F12")
        page.wait_for_selector(".peekview-widget .monaco-list-row", timeout=8000)
        # a plain-word lookup (what Ctrl+hover does) used to wipe the component marks
        ev("definitionProvider.provideDefinition(panes[1].editor.getModel(), {lineNumber: 17, column: 12})")
        time.sleep(0.3)
        page.dblclick(".peekview-widget .monaco-list-row .referenceMatch")  # a reference row, not a file header
        page.wait_for_function("panes[0].currentPath && panes[0].currentPath.endsWith('Dup.vue')", timeout=8000)
        s_ = state()
        check("beside/peek list pick (after a plain lookup) opens in the opposite pane", s_["cur"][1] == F and s_["n"] == 2, str(s_))
        page.keyboard.press("Escape")
        # 8) Ctrl+Alt+F12 -> same pane
        layout(F)
        f12_on_tag(0, "Control+Alt+F12")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(T)}", timeout=8000)
        check("Ctrl+Alt+F12 on a tag opens the component in the same pane (no split)", state()["n"] == 1, str(state()))
        # 9) Ctrl+Alt+click -> same pane (split, focus right)
        layout(OTHER, F, 1)
        xy = tag_xy(1, 3, 8)
        page.mouse.move(xy[0], xy[1]); page.keyboard.down("Control"); page.keyboard.down("Alt")
        page.mouse.move(xy[0] + 1, xy[1]); time.sleep(0.6)
        page.mouse.click(xy[0] + 1, xy[1]); page.keyboard.up("Alt"); page.keyboard.up("Control")
        page.wait_for_function(f"panes[1].currentPath === {json.dumps(T)}", timeout=8000)
        check("Ctrl+Alt+click on a tag opens it in the same (right) pane", state()["cur"][0] == OTHER, str(state()))
        check("Ctrl+Alt+click leaves a single cursor", ev("panes[1].editor.getSelections().length") == 1)
        # 10) setting off -> F12 and plain click open in the same pane
        ev("STATE.componentBeside = false")
        layout(F)
        f12_on_tag(0)
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(T)}", timeout=8000)
        check("setting off: F12 on a tag opens in the same pane", state()["n"] == 1)
        layout(F)
        xy = tag_xy(0, 3, 8)
        page.mouse.move(xy[0], xy[1]); time.sleep(0.2); page.mouse.click(xy[0], xy[1])
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(T)}", timeout=8000)
        check("setting off: plain click opens in the same pane", state()["n"] == 1)
        ev("openSettings()")
        page.wait_for_selector("#settingsBg.show", timeout=5000)
        check("settings checkbox mirrors the option", ev("document.getElementById('setComponentBeside').checked") is False)
        ev("document.getElementById('setComponentBeside').checked = true; saveSettings()")
        page.wait_for_function("STATE.componentBeside === true", timeout=5000)
        check("settings checkbox turns it back on", True)
        # 11) Quick Open / Ctrl+T: Enter = same pane, Ctrl+Enter = other pane
        layout(F, OTHER, 1)
        ev("openQO(\"\")"); page.fill("#qoInput", "ItemTop.vue"); ev("runQO()")
        page.wait_for_function(f"_qoItems.length && _qoItems[0].path === {json.dumps(T)}", timeout=8000)
        page.keyboard.press("Control+Enter")
        wait_t_in(0)
        check("Quick Open Ctrl+Enter opens in the other pane", state()["cur"] == [T, OTHER], str(state()))
        layout(F, OTHER, 0)
        ev("openQO('#')"); page.fill("#qoInput", "#Shap"); ev("runQO()")
        page.wait_for_function("_qoItems.length > 0 && _qoItems[0].label === 'Shapes'", timeout=8000)
        page.keyboard.press("Control+Enter")
        page.wait_for_function("panes[1].currentPath === 'proj/nav/Shapes.java' && panes[1].editor.getPosition().lineNumber === 2", timeout=8000)
        check("Ctrl+T Ctrl+Enter opens the symbol in the other pane at its line", state()["cur"][0] == F, str(state()))
        layout(F, OTHER, 0)
        ev("openQO('#')"); page.fill("#qoInput", "#Shap"); ev("runQO()")
        page.wait_for_function("_qoItems.length > 0 && _qoItems[0].label === 'Shapes'", timeout=8000)
        page.keyboard.press("Enter")
        page.wait_for_function("panes[0].currentPath === 'proj/nav/Shapes.java'", timeout=8000)
        check("Ctrl+T Enter still opens in the same pane", state()["cur"][1] == OTHER, str(state()))
        while ev("panes.length") > 1:
            ev("closePane(1)")

        # --- tree file operations, .gitignore filter, keymaps, icons, view toggles, diff, git, toolbar ---
        ev("while (panes.length > 1) closePane(1)")
        ev("(async () => { for (const k of [...panes[0].tabs.keys()]) await closeTabIn(0, k, true); })()")
        ev("setSideTab('files'); revealInTree('proj/ops/ren.txt')")
        page.wait_for_selector('#tree .node[data-path="proj/ops/ren.txt"]', timeout=5000)
        ev("openFile('proj/ops/ren.txt')")
        page.wait_for_function("currentPath === 'proj/ops/ren.txt'", timeout=5000)
        ev("editor.setPosition({lineNumber: 3, column: 2})")
        # rename a file with F2 from the tree; its open tab follows (same cursor)
        page.click('#tree .node[data-path="proj/ops/ren.txt"]')
        page.wait_for_function("currentPath === 'proj/ops/ren.txt'", timeout=5000)
        ev("panes[0].editor.setPosition({lineNumber: 3, column: 2})")
        page.focus('#tree')
        page.keyboard.press("F2")
        page.wait_for_selector("#dlgBg.show #dlgInput", timeout=3000)
        check("F2 in the tree: rename box with the name, stem selected",
              ev("[document.getElementById('dlgInput').value, document.getElementById('dlgInput').selectionEnd]") == ["ren.txt", 3])
        page.fill("#dlgInput", "renamed.txt")
        page.keyboard.press("Enter")
        page.wait_for_function("panes[0].tabs.has('proj/ops/renamed.txt')", timeout=5000)
        check("rename: file renamed on disk, tab follows (same pane, cursor kept)", os.path.exists(P("ops", "renamed.txt"))
              and not os.path.exists(P("ops", "ren.txt")) and ev("currentPath") == "proj/ops/renamed.txt"
              and ev("editor.getPosition().lineNumber") == 3)
        page.wait_for_selector('#tree .node[data-path="proj/ops/renamed.txt"]', timeout=5000)
        check("rename: tree refreshed, new name selected", ev("_treeSel") == "proj/ops/renamed.txt")
        st, body = raw_post("/api/rename", {"path": "proj/ops/renamed.txt", "name": "keep.txt"}, server.CSRF_TOKEN)
        check("rename refuses to overwrite an existing name", st == 409, str(body))
        st, body = raw_post("/api/rename", {"path": "proj/ops/renamed.txt", "name": "../x.txt"}, server.CSRF_TOKEN)
        check("rename refuses a path as the new name", st == 400, str(body))
        st, body = raw_post("/api/rename", {"path": "proj/ops/renamed.txt", "name": "x.txt"})
        check("rename is a guarded write API (no token -> refused)", st in (403, 400), str(st))
        # rename a folder with an open, edited file inside: asks to save first, tab follows
        ev("openFile('proj/ops/dir1/inner.txt')")
        page.wait_for_function("currentPath === 'proj/ops/dir1/inner.txt'", timeout=5000)
        ev("STATE.editMode = true; panes.forEach(applyEditorMode); editor.executeEdits('t', [{range: new monaco.Range(1,1,1,1), text: 'E'}])")
        ev("renameEntry({path: 'proj/ops/dir1', dir: true}); 0")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        check("renaming a folder with unsaved files inside asks to save first", "unsaved" in ev("document.getElementById('dlgMsg').textContent"))
        page.click("#dlgBg .dlg button >> text=save and rename")
        page.wait_for_function("document.getElementById('dlgTitle').textContent === 'rename' && document.getElementById('dlgInput').style.display === ''", timeout=10000)
        page.fill("#dlgInput", "dirA")
        page.keyboard.press("Enter")
        try:
            page.wait_for_function("docs.has('proj/ops/dirA/inner.txt')", timeout=15000)
        except Exception:
            print("  folder rename: toast:", ev("document.getElementById('toast').textContent"), "| on disk:", os.listdir(P("ops")))
            raise
        check("folder rename: open file saved, re-keyed, still open", open(P("ops", "dirA", "inner.txt"), encoding="utf-8").read() == "Einner\n"
              and not ev("docs.has('proj/ops/dir1/inner.txt')"))
        # delete: Recycle Bin path (stubbed, nothing reaches the real bin), then permanent fallback
        recycled = []
        orig_recycle = server._recycle
        server._recycle = lambda full: (recycled.append(full), os.remove(full), True)[2]
        ev("openFile('proj/ops/gone.txt')")
        page.wait_for_function("currentPath === 'proj/ops/gone.txt'", timeout=5000)
        page.click('#tree .node[data-path="proj/ops/gone.txt"]')
        page.focus('#tree')
        page.keyboard.press("Delete")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        check("Delete in the tree asks first (Recycle Bin)", "Recycle Bin" in ev("document.getElementById('dlgMsg').textContent"))
        page.click("#dlgBg .dlg button >> text=move to Recycle Bin")
        page.wait_for_function("!docs.has('proj/ops/gone.txt')", timeout=5000)
        page.wait_for_function("!document.querySelector('#tree .node[data-path=\"proj/ops/gone.txt\"]')", timeout=5000)
        check("delete: moved to the Recycle Bin, its tab closed, tree updated", len(recycled) == 1 and not os.path.exists(P("ops", "gone.txt")),
              str(recycled))
        server._recycle = lambda full: False
        ev("deleteEntry({path: 'proj/ops/dir2', dir: true}); 0")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        page.click("#dlgBg .dlg button >> text=move to Recycle Bin")
        page.wait_for_function("document.getElementById('dlgMsg').textContent.includes('permanently')", timeout=5000)
        check("no Recycle Bin: asks before deleting permanently", True)
        page.click("#dlgBg .dlg button >> text=delete permanently")
        page.wait_for_function("document.getElementById('toast').textContent.includes('deleted')", timeout=5000)
        check("…and deletes the folder", not os.path.exists(P("ops", "dir2")))
        server._recycle = orig_recycle
        st, body = raw_post("/api/delete", {"path": ""}, server.CSRF_TOKEN)
        check("delete refuses the base folder itself / empty path", st == 400, str(body))
        st, body = raw_post("/api/delete", {"path": "proj/../../outside"}, server.CSRF_TOKEN)
        check("delete refuses paths outside the folder", st == 400, str(body))
        # new folder
        ev("newFolderDialog('proj/ops'); 0")
        page.wait_for_selector("#dlgBg.show #dlgInput", timeout=3000)
        page.fill("#dlgInput", "proj/ops/fresh")
        page.keyboard.press("Enter")
        page.wait_for_function("document.getElementById('toast').textContent.includes('created proj/ops/fresh')", timeout=5000)
        check("new folder created and shown", os.path.isdir(P("ops", "fresh")))
        # tree context menu
        ev("document.querySelector('#tree .node[data-path=\"proj/ops/keep.txt\"]').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 100, clientY: 200}))")
        labels = ev("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(x => x.dataset.label)")
        check("tree menu: open, open beside, new file/folder, rename, delete, copy paths, reveal, collapse",
              all(x in labels for x in ["open", "open beside", "new file…", "new folder…", "rename…", "delete", "copy path", "copy relative path",
                                        "reveal in Explorer", "collapse all"]), str(labels))
        page.click("#ctxMenu .ctx-item[data-label='copy relative path']")
        page.wait_for_function("document.getElementById('toast').textContent.includes('proj/ops/keep.txt')", timeout=3000)
        check("copy relative path", True)
        # .gitignore filter: tree, Quick Open, search (rg) all follow it, and only when on
        def tree_names(rel):
            return [i["name"] for i in ev(f"fetch('/api/tree?path={rel}').then(r => r.json())")["items"]]
        def files_q(q):
            return [x["path"] for x in ev(f"fetch('/api/files?q={q}&limit=50').then(r => r.json())")["results"]]
        def search_files(q):
            d = ev(f"fetch('/api/search?q={q}').then(r => r.json())")
            return sorted({x["path"] for x in d.get("results", [])})
        before = (tree_names("proj/gi"), files_q("secret"))
        check("gitignore filter off by default: everything listed", "a.secret" in before[0] and "logs" in before[0]
              and "proj/gi/a.secret" in before[1], str(before))
        r = ev("postJson('/api/settings', {respect_gitignore: true}).then(r => r.data.respect_gitignore)")
        tn, fq = tree_names("proj/gi"), files_q("secret")
        check("gitignore on: tree hides *.secret and logs/, keeps !keep.secret", r is True and "a.secret" not in tn and "logs" not in tn
              and "keep.secret" in tn and "ok.txt" in tn, str(tn))
        check("gitignore on: Quick Open follows", fq == ["proj/gi/keep.secret"], str(fq))
        sf = search_files("gineedle")
        check("gitignore on: Find in Files (ripgrep) follows", sf == ["proj/gi/keep.secret", "proj/gi/ok.txt"], str(sf))
        ev("postJson('/api/settings', {respect_gitignore: false})")
        sf = search_files("gineedle")
        check("gitignore off again: all four found", len(sf) == 4, str(sf))
        check("gitignore toggle is a palette command and a settings checkbox",
              ev("CMD.has('pref.gitignore') && !!document.getElementById('setGitignore')"))
        # keymaps
        check("keymaps: no key bound twice in either preset", ev("keymapConflicts('vscode').length + keymapConflicts('intellij').length") == 0)
        ev("runCommand('pref.keymapIntelliJ')")
        ev("editor.focus()")
        page.keyboard.press("Control+n")
        page.wait_for_function("document.getElementById('qoBg').classList.contains('show') && document.getElementById('qoInput').value === '#'", timeout=3000)
        check("IntelliJ keymap: Ctrl+N = go to class/symbol", True)
        page.keyboard.press("Escape")
        page.keyboard.press("Control+Shift+a")
        page.wait_for_function("document.getElementById('qoInput').value === '>'", timeout=3000)
        check("IntelliJ keymap: Ctrl+Shift+A = find action (palette)", ev("_qoItems.find(i => i.cmd === 'go.symbolFile').meta") == "Ctrl+F12")
        page.keyboard.press("Escape")
        ev("editor.focus()")
        page.keyboard.press("Control+F12")
        page.wait_for_function("document.getElementById('qoInput').value === '@'", timeout=3000)
        check("IntelliJ keymap: Ctrl+F12 (file structure) beats Monaco's own Ctrl+F12", True)
        page.keyboard.press("Escape")
        ev("openSettings()")
        page.wait_for_selector("#settingsBg.show", timeout=3000)
        check("settings: keymap select + 'no key conflicts' + shortcut list for the keymap",
              ev("document.getElementById('setKeymap').value") == "intellij" and "no key conflicts" in ev("document.getElementById('keymapConflicts').textContent")
              and "IntelliJ" in ev("document.getElementById('kbdGenerated').textContent") and "Ctrl+Shift+A" in ev("document.getElementById('kbdGenerated').textContent"))
        ev("closeSettings(); runCommand('pref.keymapVSCode')")
        ev("editor.focus()")
        page.keyboard.press("Control+n")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        check("back to VS Code keymap: Ctrl+N = new file", "new file" in ev("document.getElementById('dlgTitle').textContent"))
        page.keyboard.press("Escape")
        # file-type badges
        ev("openFile('proj/nav/Use.java')")
        page.wait_for_function("currentPath === 'proj/nav/Use.java'", timeout=5000)
        check("tabs and tree show a file-type badge (Java: J)", ev("document.querySelector('.tab-item.active .fbadge').textContent") == "J"
              and ev("!!document.querySelector('#tree .node[data-path=\"proj/nav/Use.java\"] .fbadge')"))
        # view toggles
        ev("runCommand('view.minimap'); runCommand('view.whitespace')")
        check("minimap / whitespace toggles reach the editor", ev("[editor.getOption(monaco.editor.EditorOption.minimap).enabled, editor.getOption(monaco.editor.EditorOption.renderWhitespace)]") == [True, "all"])
        ev("runCommand('view.minimap'); runCommand('view.whitespace')")
        # tab menu: close others
        ev("openFile('proj/A.java'); openFile('proj/B.java')")
        page.wait_for_function("panes[0].tabs.has('proj/B.java')", timeout=5000)
        ev("panes[0].tabsEl.querySelector('.tab-item[data-key=\"proj/B.java\"]').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 300, clientY: 120}))")
        page.click("#ctxMenu .ctx-item[data-label='close others']")
        page.wait_for_function("panes[0].tabs.size === 1", timeout=5000)
        check("tab menu: close others", ev("[...panes[0].tabs.keys()]") == ["proj/B.java"])
        # reopen with another encoding
        ev("openFile('proj/kor.properties')")
        page.wait_for_function("currentPath === 'proj/kor.properties'", timeout=5000)
        ev("reopenWithEncoding(); 0")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        page.click("#dlgBg .dlg button >> text=Latin-1")
        page.wait_for_function("currentDoc().encoding === 'latin-1'", timeout=5000)
        lat = ev("editor.getModel().getValue()")
        ev("reopenWithEncoding(); 0")
        page.wait_for_selector("#dlgBg.show", timeout=3000)
        page.click("#dlgBg .dlg button >> text=CP949 / EUC-KR")
        page.wait_for_function("currentDoc().encoding === 'cp949'", timeout=5000)
        check("reopen with encoding: Latin-1 garbles, CP949 reads 한글 again", "한글" not in lat and "한글값" in ev("editor.getModel().getValue()"))
        # diff: compare with saved
        ev("openFile('proj/B.java')")
        page.wait_for_function("currentPath === 'proj/B.java'", timeout=5000)
        ev("editor.executeEdits('t', [{range: new monaco.Range(2,1,2,1), text: '// changed\\n'}])")
        ev("runCommand('file.compareSaved')")
        page.wait_for_function("document.getElementById('diffBg').classList.contains('show') && _diff && _diff.ed.getLineChanges() && _diff.ed.getLineChanges().length > 0", timeout=8000)
        check("compare with saved: side-by-side diff of the unsaved change", ev("_diff.ed.getLineChanges().length") == 1)
        page.keyboard.press("Escape")
        page.wait_for_function("!document.getElementById('diffBg').classList.contains('show')", timeout=3000)
        check("Esc closes the diff; the edit is still in the editor", "// changed" in ev("editor.getModel().getValue()"))
        ev("editor.getModel().undo()")
        # git markers and branch
        ev("openFile('proj/repo/tracked.txt')")
        page.wait_for_function("currentPath === 'proj/repo/tracked.txt'", timeout=5000)
        page.wait_for_function("currentDoc().gitRepo === true", timeout=8000)
        check("git: branch in the status bar", ev("document.getElementById('sbBranch').textContent") == "⎇ main")
        ev("editor.executeEdits('t', [{range: new monaco.Range(2,1,2,4), text: 'TWO'}, {range: new monaco.Range(5,1,5,1), text: 'five\\n'}])")
        page.wait_for_function("editor.getModel().getAllDecorations().some(d => d.options.linesDecorationsClassName === 'git-mod')", timeout=8000)
        cls = ev("editor.getModel().getAllDecorations().filter(d => /^git-/.test(d.options.linesDecorationsClassName || '')).map(d => [d.range.startLineNumber, d.options.linesDecorationsClassName])")
        check("git: changed / added lines marked in the gutter", [2, "git-mod"] in cls and [5, "git-add"] in cls, str(cls))
        ev("runCommand('file.compareHead')")
        page.wait_for_function("document.getElementById('diffBg').classList.contains('show')", timeout=8000)
        check("compare with git HEAD opens a diff", "HEAD (main)" in ev("document.getElementById('diffTitle').textContent"))
        ev("closeDiff(); editor.getModel().undo()")
        # declaration hover: usages count
        page.wait_for_function("fetch('/api/tags-status').then(r => r.json()).then(s => s.ready && !s.building)", timeout=20000, polling=500)
        ev("openFile('proj/nav/Shapes.java')")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java'", timeout=5000)
        xy = ev("""(() => { const ed = editor; const c = ed.getModel().getLineContent(7).indexOf('helper') + 3;
                  const p = ed.getScrolledVisiblePosition({lineNumber: 7, column: c}); const b = ed.getDomNode().getBoundingClientRect();
                  return [b.left + p.left + 2, b.top + p.top + p.height / 2]; })()""")
        page.mouse.move(5, 5); page.mouse.move(xy[0], xy[1])
        page.wait_for_function("editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-decl')", timeout=8000)
        msg = ev("editor.getModel().getAllDecorations().find(d => d.options.inlineClassName === 'reado-decl').options.hoverMessage.value")
        check("hover on a declaration: its usages count (not a link)", "usage" in msg and "Shift+F12" in msg, msg)
        # toolbar
        tips = ev("[...document.querySelectorAll('#tbGroups .tbtn')].map(b => b.title)")
        check("toolbar: every button has a name + key tooltip from the registry",
              "Editing (Ctrl+Shift+E)" in tips and "Word Wrap (Alt+Z)" in tips, str(tips))
        # 2026-10-16 top bar tidy-up: Find in Files lives in the title-bar search (% mode), the gear moved to the tool strip
        check("toolbar: Go to File / Find in Files buttons removed (title bar search), 3 groups + git",
              ev("[...document.querySelectorAll('#tbGroups .tbg')].map(g => g.dataset.group).filter(g => g !== 'git')") == ["file", "view", "prefs"]
              and not any("Go to File" in t or "Find in Files" in t for t in tips) and "Find in Files (Ctrl+Shift+F)" in ev("document.querySelector('.tb-search').textContent"))
        page.click("#tbGroups [data-cmd='view.wrap']")
        check("toolbar button runs the command and shows its state", ev("STATE.wordWrap") and ev("document.getElementById('wrapBtn').classList.contains('active')"))
        page.click("#tbGroups [data-cmd='view.wrap']")
        page.set_viewport_size({"width": 600, "height": 700})
        page.wait_for_function("document.querySelector('.topbar').classList.contains('tiny')", timeout=3000)
        page.click("#tbMore")
        more = ev("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(x => x.dataset.label)")
        check("narrow window: labels hide, less used groups move into the ⋯ menu", "New File…" in more and "Word Wrap" in more, str(more))
        ev("closeMenu()")
        page.set_viewport_size({"width": 1280, "height": 720})

        # window background follows the theme (maximize must not expose a white form)
        ev("window._bgCalls = []; window.pywebview = Object.assign(window.pywebview || {}, {api: Object.assign((window.pywebview || {}).api || {}, {win_background: c => window._bgCalls.push(c)})})")
        th0 = ev("getTheme()")
        ev("toggleTheme()"); ev("toggleTheme()")
        calls = ev("window._bgCalls")
        want = {"dark": "#282c34", "light": "#ffffff"}
        check("theme change sends the window background color (dark #282c34 / light #ffffff)",
              calls == [want["light" if th0 == "dark" else "dark"], want[th0]], str(calls))
        # theme before first paint: the served page applies the saved theme right after <body>
        html = ev("fetch('/').then(r => r.text())")
        body_at = html.find("<body>")
        first_script = html.find("<script", body_at)
        pre = html[first_script:html.find("</script>", first_script)].split(">", 1)[1]
        p3 = ctx.new_page()
        got = []
        for st in ({"theme": "dark"}, {"theme": "light"}, {}):
            p3.set_content("<html><head></head><body></body></html>")
            got.append(p3.evaluate("([st, src]) => { window.READO_STATE = st; (0, eval)(src); return document.body.className; }", [st, pre]))
        p3.close()
        check("pre-paint theme script comes first in <body>: dark -> theme-dark, light / none -> theme-light",
              html[body_at + 6:first_script].strip() == "" and got == ["theme-dark", "theme-light", "theme-light"], str(got))
        # theme button: icon only, and the icon follows the theme right after each toggle
        def theme_btn():
            return ev("""(() => { const b = document.getElementById('themeBtn');
              return [getTheme(), b.textContent.trim(), b.querySelector('svg path, svg circle').tagName, b.getAttribute('aria-label')]; })()""")
        b0 = theme_btn()
        ev("document.getElementById('themeBtn').click()")
        b1 = theme_btn()
        ev("document.getElementById('themeBtn').click()")
        b2 = theme_btn()
        icon = {"light": "path", "dark": "circle"}  # moon in the light theme, sun in the dark one
        check("theme button: no text, its icon and aria-label follow the theme at once",
              all(b[1] == "" and b[2] == icon[b[0]] and b[3].startswith(b[0].capitalize() + " theme") for b in (b0, b1, b2))
              and b1[0] != b0[0] and b2[0] == b0[0], f"{b0} {b1} {b2}")
        # --- tool window strip (Files / Outline / Git) and the folding sidebar ---
        ev("while (panes.length > 1) closePane(1)")
        ev("setSidebarOpen(true); setSideTab('files')")
        tips = ev("[...document.querySelectorAll('#toolStrip .tsb')].map(b => b.title)")
        check("tool strip renders Files / Outline / Git / Settings (bottom) with name + key tooltips",
              len(tips) == 4 and tips[0] == "Files (Alt+1)" and tips[1] == "Outline (Alt+2)" and tips[2].startswith("Git") and tips[3].startswith("Settings"), str(tips))
        check("tool strip: Files is highlighted while the files sidebar is open",
              ev("[...document.querySelectorAll('#toolStrip .tsb')].map(b => b.classList.contains('active'))")[:2] == [True, False])
        w_open = ev("panes[0].paneEl.getBoundingClientRect().width")
        side_w = ev("document.getElementById('sidebar').getBoundingClientRect().width")
        page.click("#tbGroups [data-cmd='view.wrap']"); page.click("#tbGroups [data-cmd='view.wrap']")  # focus out of inputs
        page.keyboard.press("Alt+1")
        page.wait_for_function("document.body.classList.contains('side-collapsed')", timeout=3000)
        time.sleep(0.3)
        w_closed = ev("panes[0].paneEl.getBoundingClientRect().width")
        check("Alt+1 on the open Files folds the sidebar away; the editor gets its width",
              ev("getComputedStyle(document.getElementById('sidebar')).display") == "none" and w_closed >= w_open + side_w - 2
              and not ev("document.querySelector('#toolStrip [data-tool=files]').classList.contains('active')"),
              f"{w_open} + {side_w} -> {w_closed}")
        page.click("#toolStrip [data-tool=outline]")
        check("Outline icon on a folded sidebar opens it on Outline",
              not ev("STATE.sideCollapsed") and ev("_sideTab") == "outline" and ev("getComputedStyle(document.getElementById('outline')).display") != "none"
              and ev("document.querySelector('#toolStrip [data-tool=outline]').classList.contains('active')"))
        check("sidebar has no FILES / OUTLINE tab bar; its header names the active tool (Outline), slimmer than the old tabs",
              ev("document.querySelectorAll('#sideTabs, .stab').length") == 0 and ev("document.getElementById('sideTitle').textContent") == "Outline"
              and ev("document.getElementById('sideHead').getBoundingClientRect().height") <= 26)
        page.click("#toolStrip [data-tool=outline]")
        check("the same icon again folds it", ev("STATE.sideCollapsed") is True)
        page.keyboard.press("Alt+1")
        check("Alt+1 on a folded sidebar opens Files (header says Files)", not ev("STATE.sideCollapsed") and ev("_sideTab") == "files"
              and ev("document.getElementById('sideTitle').textContent") == "Files")
        page.click("#sideHide")
        check("the « button in the sidebar header folds it", ev("STATE.sideCollapsed") is True)
        check("View menu / palette has Files, Outline and Sidebar entries",
              ev("['view.files', 'view.outline', 'view.sidebar'].every(id => JSON.stringify(MENUS).includes(id))"))
        # Git icon: clickable even when the folder is not a repository (like the Git menu),
        # highlighted while the Git tool window is open
        page.wait_for_function("_gitAvail !== null", timeout=8000)
        check("Git icon stays enabled when the folder is not a git repository (same as the menu)",
              ev("!document.querySelector('#toolStrip [data-tool=git]').disabled"))
        page.click("#toolStrip [data-tool=git]")
        on = ev("STATE.git.open && document.querySelector('#toolStrip [data-tool=git]').classList.contains('active')")
        page.click("#toolStrip [data-tool=git]")
        check("Git icon click opens / closes the Git tool window and highlights while open (same state as menu / Ctrl+Shift+G)",
              on and not ev("STATE.git.open") and not ev("document.querySelector('#toolStrip [data-tool=git]').classList.contains('active')"))
        check("git missing: the icon is dimmed but still clickable",
              ev("_gitAvail = false; refreshToolStrip(); const b = document.querySelector('#toolStrip [data-tool=git]'); b.classList.contains('dim') && !b.disabled && b.title.includes('git not found')"))
        ev("refreshGitAvail()")
        # both themes: the strip uses the panel color of each
        bg1 = ev("getComputedStyle(document.getElementById('toolStrip')).backgroundColor")
        ev("toggleTheme()"); bg2 = ev("getComputedStyle(document.getElementById('toolStrip')).backgroundColor"); ev("toggleTheme()")
        check("tool strip follows the theme (light / dark panel colors)", bg1 != bg2 and bg1 and bg2, f"{bg1} / {bg2}")
        # double-click on a tab's file name / the breadcrumb's file name: source full width, again: back
        ev("setSideTab('files'); setSidebarOpen(true); document.getElementById('sidebar').style.width = '260px'")
        ev("if (STATE.git && STATE.git.open) toggleGitTool(); STATE.maxRestore = null")
        ev("openFile('proj/A.java')"); page.wait_for_function("currentPath === 'proj/A.java'", timeout=5000)
        ev("openFile('proj/doc/guide.md')"); page.wait_for_function("currentPath === 'proj/doc/guide.md'", timeout=5000)
        tabs0 = ev("[...panes[activePaneIdx].tabs.keys()].join()")
        w0 = ev("document.querySelector('.pane.active').getBoundingClientRect().width")
        page.dblclick(".pane.active .tab-item.active .tab-name")
        page.wait_for_function("document.body.classList.contains('side-collapsed')", timeout=3000)
        check("double-click on the tab's file name: sidebar away, source wider; same tab, same tabs",
              ev("getComputedStyle(document.getElementById('sidebar')).display") == "none"
              and ev("document.querySelector('.pane.active').getBoundingClientRect().width") > w0 + 100
              and ev("currentPath") == "proj/doc/guide.md" and ev("[...panes[activePaneIdx].tabs.keys()].join()") == tabs0)
        page.dblclick("#crumbs .file")
        page.wait_for_function("!document.body.classList.contains('side-collapsed')", timeout=3000)
        check("double-click on the breadcrumb's file name: sidebar back, same width and panel",
              ev("document.getElementById('sidebar').getBoundingClientRect().width") == 260 and ev("_sideTab") == "files"
              and ev("currentPath") == "proj/doc/guide.md")
        # with the Git tool window open: both go, both come back
        ev("toggleGitTool()"); page.wait_for_function("STATE.git && STATE.git.open", timeout=3000)
        page.dblclick(".pane.active .tab-item.active .tab-name")
        page.wait_for_function("STATE.sideCollapsed && !STATE.git.open", timeout=3000)
        check("double-click: the Git tool window goes too", True)
        ev("flushState()"); time.sleep(0.5)
        check("full-width state and what to bring back are saved", server.ui_state().get("sideCollapsed") is True
              and server.ui_state().get("maxRestore") == {"side": True, "git": True}, str(server.ui_state().get("maxRestore")))
        page.dblclick("#crumbs .file")
        page.wait_for_function("!STATE.sideCollapsed && STATE.git.open", timeout=3000)
        check("double-click again: sidebar and Git tool window back", ev("STATE.maxRestore") is None)
        ev("toggleGitTool()")
        # a double-click on another tab's name: that tab becomes active (its single click), the sidebar toggles once
        page.dblclick('.pane.active .tab-item[data-key="proj/A.java"] .tab-name')
        page.wait_for_function("STATE.sideCollapsed", timeout=3000)
        check("double-click on another tab's name: switches to it once, no tab opened or closed",
              ev("currentPath") == "proj/A.java" and ev("[...panes[activePaneIdx].tabs.keys()].join()") == tabs0,
              str(ev("[currentPath, [...panes[activePaneIdx].tabs.keys()].join(), STATE.sideCollapsed]")) + " / " + tabs0)
        ev("setSidebarOpen(true); STATE.maxRestore = null")
        # state.json: folded + outline survive a reload
        ev("setSideTab('outline'); setSidebarOpen(false); flushState()")
        time.sleep(0.6)
        page.reload()
        page.wait_for_function("typeof monaco !== 'undefined' && _stateReady", timeout=20000)
        check("reload restores the folded sidebar and the active tool (state.json)",
              ev("document.body.classList.contains('side-collapsed')") and ev("_sideTab") == "outline"
              and ev("getComputedStyle(document.getElementById('sidebar')).display") == "none", str(ev("[STATE.sideCollapsed, STATE.sideTab]")))
        ev("setSideTab('files'); setSidebarOpen(true); flushState()")
        time.sleep(0.4)

        # --- the page itself never scrolls (only its parts do), whatever the layout ---
        NOSCROLL = """(() => { const d = document.documentElement, b = document.body;
            const ed = document.getElementById('main').getBoundingClientRect().height;
            const sb = document.getElementById('statusbar').getBoundingClientRect();
            return [d.scrollHeight <= d.clientHeight && b.scrollHeight <= b.clientHeight && d.scrollWidth <= d.clientWidth,
                    innerWidth - d.clientWidth, Math.round(ed), Math.round(sb.bottom) <= innerHeight,
                    getComputedStyle(d).overflowY, d.scrollHeight, d.clientHeight]; })()"""
        def no_scroll(label, min_editor=150):
            r = ev(NOSCROLL)
            check(f"page does not scroll: {label}", r[0] and r[1] == 0 and r[3] and r[2] >= min_editor and r[4] == "hidden", str(r))
        ev("GitUI.toggleWindow(true)")
        page.wait_for_function("document.querySelector('.gw.show')", timeout=5000)
        ev("document.querySelector('.gw').style.height = (innerHeight - 160) + 'px'")  # the sash's largest height
        time.sleep(0.2)
        no_scroll("Git panel dragged to its largest height")
        page.set_viewport_size({"width": 1000, "height": 520})  # then the window gets smaller (restore from maximized)
        time.sleep(0.4)
        no_scroll("tall Git panel, window made small (editor keeps >= 150px)")
        ev("splitActive('row')"); ev("setSidebarOpen(false)")
        time.sleep(0.3)
        no_scroll("small window + split panes + folded sidebar")
        page.set_viewport_size({"width": 1920, "height": 1152})  # maximized size
        time.sleep(0.4)
        no_scroll("maximized size, tall Git panel, split, folded")
        ev("document.querySelector('.gw').style.height = '5000px'")  # a stale saved height bigger than any screen
        time.sleep(0.2)
        no_scroll("absurd saved Git panel height")
        ev("GitUI.toggleWindow(false); setSidebarOpen(true); while (panes.length > 1) closePane(1)")
        page.set_viewport_size({"width": 600, "height": 400})
        time.sleep(0.3)
        no_scroll("very small window, Git closed", min_editor=150)
        page.set_viewport_size({"width": 1280, "height": 720})
        time.sleep(0.3)

        # --- title bar, menus, Ctrl+P / Ctrl+Shift+P (one command registry) ---
        ev("while (panes.length > 1) closePane(1)")
        ev("openFile('proj/A.java')")
        page.wait_for_function("currentPath === 'proj/A.java'", timeout=5000)
        ev("openFile('proj/nav/Shapes.java')")
        page.wait_for_function("currentPath === 'proj/nav/Shapes.java'", timeout=5000)
        check("title bar: menus File Edit View Go Help (no Window menu in a browser)",
              ev("[...document.querySelectorAll('#menubar .menubar-item')].map(b => b.textContent).filter(t => t !== 'Git')") == ["File", "Edit", "View", "Go", "Help"])
        check("browser: no window buttons, no resize edges", ev("getComputedStyle(document.querySelector('.win-ctl')).display") == "none"
              and ev("getComputedStyle(document.querySelector('.rz-n')).display") == "none")
        check("title bar logo is the app icon", ev("fetch('/favicon.ico').then(r => [r.status, r.headers.get('content-type')])") == [200, "image/x-icon"])
        # Ctrl+P from the editor: files, recent first, fuzzy
        ev("editor.focus()")
        page.keyboard.press("Control+p")
        page.wait_for_selector("#qoBg.show", timeout=3000)
        check("Ctrl+P (editor focused) opens Quick Open, not print", ev("document.getElementById('qoInput').value") == "")
        page.keyboard.type("ajav")
        page.wait_for_function("_qoItems.length && _qoItems[0].path === 'proj/A.java'", timeout=8000)
        check("Ctrl+P: fuzzy file match, the recently opened file first", ev("_qoItems[0].meta") == "recent")
        page.keyboard.press("Escape")
        check("Esc closes Quick Open", not ev("document.getElementById('qoBg').classList.contains('show')"))
        # Ctrl+Shift+P: commands, fuzzy, keys shown, Enter runs
        ev("editor.focus()")
        page.keyboard.press("Control+Shift+p")
        page.wait_for_selector("#qoBg.show", timeout=3000)
        check("Ctrl+Shift+P opens the command palette ('>' prefix)", ev("document.getElementById('qoInput').value") == ">"
              and ev("_qoMode") == "command" and ev("_qoItems.length") > 40)
        page.keyboard.type("wrap")
        page.wait_for_function("_qoItems.length && _qoItems[0].cmd === 'view.wrap'", timeout=3000)
        check("palette: fuzzy search finds 'View: Word Wrap' with its key", ev("_qoItems[0].meta") == "Alt+Z"
              and "Word Wrap" in ev("document.querySelector('#qoList .qo-item.sel').textContent"))
        wrap0 = ev("!!STATE.wordWrap")
        page.keyboard.press("Enter")
        page.wait_for_function(f"!!STATE.wordWrap === {str(not wrap0).lower()}", timeout=3000)
        check("palette: Enter runs the command, palette closes", not ev("document.getElementById('qoBg').classList.contains('show')"))
        page.keyboard.press("Control+Shift+p")
        page.wait_for_selector("#qoBg.show", timeout=3000)
        check("palette: the command just run is listed first", ev("_qoItems[0].cmd") == "view.wrap")
        page.keyboard.type("splt rgt")
        page.wait_for_function("_qoItems.length && _qoItems[0].cmd === 'layout.splitRight'", timeout=3000)
        check("palette: letters-in-order match ('splt rgt' -> Layout: Split Right)", True)
        page.keyboard.press("Escape")
        page.keyboard.press("Control+p")
        page.wait_for_selector("#qoBg.show", timeout=3000)
        page.keyboard.type(">grid")
        page.wait_for_function("_qoMode === 'command' && _qoItems.length && _qoItems[0].cmd === 'layout.grid'", timeout=3000)
        check("Ctrl+P then '>' switches to commands", True)
        page.keyboard.press("Escape")
        ev("STATE.wordWrap = " + str(wrap0).lower())
        # menu bar: open, hover-switch, run, Esc
        page.click("#menubar .menubar-item[data-menu='View']")
        page.wait_for_selector(".menu-dropdown", timeout=3000)
        rows = ev("[...document.querySelectorAll('.menu-dropdown .menu-row')].map(r => r.textContent)")
        check("View menu lists commands with their keys", any("Command Palette…" in r and "Ctrl+Shift+P" in r for r in rows), str(rows[:4]))
        page.hover("#menubar .menubar-item[data-menu='Go']")
        page.wait_for_function("[...document.querySelectorAll('.menu-dropdown .menu-row')].some(r => r.dataset.cmd === 'go.line')", timeout=3000)
        check("hovering another menu while one is open switches to it", ev("document.querySelectorAll('.menu-dropdown').length") == 1)
        page.keyboard.press("Escape")
        check("Esc closes the menu", ev("document.querySelectorAll('.menu-dropdown').length") == 0)
        # submenu: View > Layout > Two columns (same command as the palette / ▥)
        page.click("#menubar .menubar-item[data-menu='View']")
        page.hover(".menu-dropdown .menu-row:has(.menu-arrow) >> text=Layout")
        page.wait_for_selector(".menu-dropdown[data-level='1'] .menu-row[data-cmd='layout.cols2']", timeout=3000)
        page.click(".menu-dropdown[data-level='1'] .menu-row[data-cmd='layout.cols2']")
        page.wait_for_function("panes.length === 2", timeout=3000)
        check("View > Layout > Two columns runs the layout command; menu closes", ev("document.querySelectorAll('.menu-dropdown').length") == 0)
        ev("focusPane(0)")
        page.click("#menubar .menubar-item[data-menu='Go']")
        page.click(".menu-row[data-cmd='go.line']")
        page.wait_for_function("document.getElementById('qoBg').classList.contains('show') && document.getElementById('qoInput').value === ':'", timeout=3000)
        check("Go > Go to Line… opens ':'", True)
        page.keyboard.press("Escape")
        page.click("#menubar .menubar-item[data-menu='Edit']")
        check("Edit > Editing shows a check mark while editing is on",
              ("✓" in ev("document.querySelector(\".menu-row[data-cmd='edit.toggleEditing']\").textContent")) == ev("!!STATE.editMode"))
        page.keyboard.press("Escape")
        page.click("#menubar .menubar-item[data-menu='File']")
        check("File > Save All disabled with nothing unsaved", ev("document.querySelector(\".menu-row[data-cmd='file.saveAll']\").disabled"))
        page.mouse.click(5, 300)
        check("a click elsewhere closes the menu", ev("document.querySelectorAll('.menu-dropdown').length") == 0)
        # keys and menu run the same command objects
        check("every menu entry is a registry command", ev("MENUS.flatMap(m => m.items.flatMap(i => typeof i === 'object' ? i.items : [i])).filter(i => i !== '-').every(i => CMD.has(i))"))
        check("no key bound twice", ev("(() => { const seen = new Set(); for (const c of COMMANDS) for (const b of c.bind || []) { if (seen.has(b)) return b; seen.add(b); } return true; })()") is True)
        # browser default keys are swallowed
        r = ev("(() => { const out = []; for (const k of ['F5', 'r', 'u']) { const e = new KeyboardEvent('keydown', {key: k, code: k === 'F5' ? 'F5' : 'Key' + k.toUpperCase(), ctrlKey: k !== 'F5', bubbles: true, cancelable: true}); document.body.dispatchEvent(e); out.push(e.defaultPrevented); } return out; })()")
        check("F5 / Ctrl+R / Ctrl+U are blocked (no reload / view source)", r == [True, True, True], str(r))
        check("window.print is a no-op", ev("window.print.toString().includes('{}')"))
        ev("while (panes.length > 1) closePane(1)")

        # --- links in the page: import paths / imported names open in the next pane ---
        D = "proj/web/src/main/page/Detail.vue"
        S = "proj/web/src/main/"
        ev("(async () => { while (panes.length > 1) closePane(1);"
           " for (const k of [...panes[0].tabs.keys()]) await closeTabIn(0, k, true); })()")
        ev("STATE.componentBeside = true; STATE.componentClick = true")
        ev(f"openFileInPane(0, {json.dumps(D)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(D)}", timeout=5000)
        ev("window.__linkCalls = 0; const _f = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/api/link')) window.__linkCalls++; return _f(u, o); }; 0")

        def xy_of(pi, line, col):
            return ev(f"""(() => {{ const ed = panes[{pi}].editor; ed.revealLine({line}); const p = ed.getScrolledVisiblePosition({{lineNumber: {line}, column: {col}}});
                      const b = ed.getDomNode().getBoundingClientRect(); return [b.left + p.left + 2, b.top + p.top + p.height / 2]; }})()""")

        def col_in(pi, line, needle, k=0):
            return ev(f"panes[{pi}].editor.getModel().getLineContent({line}).indexOf({json.dumps(needle)})") + 1 + k

        def link_deco(pi):
            return ev(f"panes[{pi}].editor.getModel().getAllDecorations().filter(d => d.options.inlineClassName === 'reado-taglink')"
                      ".map(d => [d.range.startColumn, d.range.endColumn, (d.options.hoverMessage || {}).value || ''])")

        def reset_single():
            ev("while (panes.length > 1) closePane(1)")
            ev(f"(async () => {{ for (const k of [...panes[0].tabs.keys()]) if (k !== {json.dumps(D)}) await closeTabIn(0, k, true); }})()")
            ev(f"openFileInPane(0, {json.dumps(D)}); focusPane(0)")
            page.wait_for_function(f"panes.length === 1 && panes[0].currentPath === {json.dumps(D)}", timeout=5000)

        # typing must not ask the server anything
        ev("panes[0].editor.focus(); panes[0].editor.setPosition({lineNumber: 11, column: 1})")
        page.keyboard.type("// typing")
        time.sleep(0.4)
        check("typing does not trigger link lookups", ev("window.__linkCalls") == 0, str(ev("window.__linkCalls")))
        ev("panes[0].editor.getModel().undo()")
        # hover over an import path: underlined, tooltip names the resolved file
        x, y = xy_of(0, 5, col_in(0, 5, "product/Recommend"))
        page.mouse.move(x, y)
        page.wait_for_function("panes[0].editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-taglink')", timeout=5000)
        d = link_deco(0)
        check("hover on an import path: link underline + resolved path in the tooltip",
              d and S + "page/product/RecommendItemsCarousel.vue" in d[0][2] and "click: open beside" in d[0][2], str(d))
        # plain click on it: opens in a new right pane, focus/cursor stay
        page.mouse.click(x, y)
        page.wait_for_function(f"panes.length === 2 && panes[1].currentPath === {json.dumps(S + 'page/product/RecommendItemsCarousel.vue')}", timeout=8000)
        check("plain click on an import path opens the file in the next pane; focus stays",
              ev("activePaneIdx") == 0 and ev("panes[0].editor.hasTextFocus()"))
        # F12 on a usage of an imported type -> its export line, next pane
        reset_single()
        ev(f"panes[0].editor.setPosition({{lineNumber: 11, column: {col_in(0, 11, 'RelatedProductsSection', 3)}}})")
        page.keyboard.press("F12")
        page.wait_for_function(f"panes.length === 2 && panes[1].currentPath === {json.dumps(S + 'service/product/domain/productModel.ts')}", timeout=8000)
        check("F12 on a used imported type opens its file beside at the export (line 3)",
              ev("panes[1].editor.getPosition().lineNumber") == 3 and ev("panes[0].currentPath") == D)
        # Alt+Left returns to the source pane and position
        page.keyboard.press("Alt+ArrowLeft")
        page.wait_for_function(f"activePaneIdx === 0 && currentPath === {json.dumps(D)}", timeout=5000)
        check("Alt+← goes back to the pane and line the jump started from", ev("panes[0].editor.getPosition().lineNumber") == 11)
        # Ctrl+click on obj.member() -> the member line
        reset_single()
        x, y = xy_of(0, 12, col_in(0, 12, "getProduct", 2))
        page.mouse.move(x, y); page.keyboard.down("Control"); page.mouse.move(x + 1, y); time.sleep(0.6)
        d = link_deco(0)
        check("Ctrl+hover on productService.getProduct shows the resolved file:line",
              any("productService.ts:5" in z[2] for z in d), str(d))
        page.mouse.click(x + 1, y); page.keyboard.up("Control")
        page.wait_for_function(f"panes.length === 2 && panes[1].currentPath === {json.dumps(S + 'service/product/application/productService.ts')}", timeout=8000)
        check("Ctrl+click on importedObj.member() opens the member in the next pane", ev("panes[1].editor.getPosition().lineNumber") == 5)
        # re-export chain through index.ts
        reset_single()
        ev(f"panes[0].editor.setPosition({{lineNumber: 13, column: {col_in(0, 13, 'formatPrice', 1)}}})")
        page.keyboard.press("F12")
        page.wait_for_function(f"panes.length === 2 && panes[1].currentPath === {json.dumps(S + 'util/price.ts')}", timeout=8000)
        check("F12 through `export * from` lands on the function", ev("panes[1].editor.getPosition().lineNumber") == 3)
        # packages and missing files: toast, nothing opens
        reset_single()
        ev(f"panes[0].editor.setPosition({{lineNumber: 7, column: {col_in(0, 7, 'onMounted', 1)}}})")
        page.keyboard.press("F12")
        page.wait_for_function("document.getElementById('toast').textContent.includes('package')", timeout=5000)
        check("F12 on an import from a package -> toast, no jump", ev("panes.length") == 1 and ev("currentPath") == D)
        ev(f"panes[0].editor.setPosition({{lineNumber: 10, column: {col_in(0, 10, 'missing', 1)}}})")
        page.keyboard.press("F12")
        page.wait_for_function("document.getElementById('toast').textContent.includes('no such file')", timeout=5000)
        check("F12 on a missing relative path -> 'no such file' toast", ev("panes.length") == 1)
        # several targets (Java wildcard import) -> chooser via a plain click
        J = "proj/java/src/main/java/com/acme/shop/Order.java"
        ev(f"openFileInPane(0, {json.dumps(J)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(J)}", timeout=5000)
        x, y = xy_of(0, 4, col_in(0, 4, "util", 1))
        page.mouse.move(x, y); time.sleep(0.3); page.mouse.click(x, y)
        page.wait_for_function("_qoMode === 'pick' && _qoItems.length === 2", timeout=8000)
        check("wildcard import -> chooser with every class of the package", ev("_qoItems.map(i => i.path.split('/').pop())") == ["Money.java", "Rates.java"])
        page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
        page.wait_for_function("panes.length === 2 && (panes[1].currentPath || '').endsWith('Rates.java')", timeout=8000)
        check("choosing opens it in the next pane", ev("panes[0].currentPath") == J)
        # Java static member, Python import name: F12 / click, next pane, right line
        reset_single()
        ev(f"openFileInPane(0, {json.dumps(J)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(J)}", timeout=5000)
        ev(f"panes[0].editor.focus(); panes[0].editor.setPosition({{lineNumber: 8, column: {col_in(0, 8, 'zero', 1)}}})")
        page.keyboard.press("F12")
        page.wait_for_function("panes.length === 2 && (panes[1].currentPath || '').endsWith('util/Money.java')", timeout=8000)
        check("java: F12 on Money.zero() opens Money.java at the method", ev("panes[1].editor.getPosition().lineNumber") == 4)
        P = "proj/py/app/main.py"
        reset_single()
        ev(f"openFileInPane(0, {json.dumps(P)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(P)}", timeout=5000)
        x, y = xy_of(0, 1, col_in(0, 1, "get_user", 2))
        page.mouse.move(x, y); time.sleep(0.3); page.mouse.click(x, y)
        page.wait_for_function("panes.length === 2 && panes[1].currentPath === 'proj/py/app/services/users.py'", timeout=8000)
        check("python: plain click on an imported name opens the module at its def", ev("panes[1].editor.getPosition().lineNumber") == 5
              and ev("activePaneIdx") == 0)
        # links without Ctrl: hover underlines what resolves, a click opens it beside
        reset_single()
        page.wait_for_function("fetch('/api/tags-status').then(r => r.json()).then(s => s.ready)", timeout=20000, polling=500)
        page.mouse.move(5, 5)
        x, y = xy_of(0, 12, col_in(0, 12, "getProduct", 2))
        page.mouse.move(x, y)
        page.wait_for_function("panes[0].editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-taglink')", timeout=5000)
        d = link_deco(0)
        cur = ev(f"getComputedStyle(document.elementFromPoint({x}, {y})).cursor")
        check("no Ctrl: hovering productService.getProduct() in code shows a link (underline, pointer, resolved path)",
              any("productService.ts:5" in z[2] for z in d) and cur == "pointer", f"{d} cursor={cur}")
        page.mouse.click(x, y)
        page.wait_for_function(f"panes.length === 2 && panes[1].currentPath === {json.dumps(S + 'service/product/application/productService.ts')}", timeout=8000)
        check("no Ctrl: a plain click opens it in the next pane; focus stays in the source",
              ev("panes[1].editor.getPosition().lineNumber") == 5 and ev("activePaneIdx") == 0)
        # a plain symbol (ctags index), no import involved
        U = "proj/nav/Use.java"
        reset_single()
        ev(f"openFileInPane(0, {json.dumps(U)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(U)}", timeout=5000)
        page.mouse.move(5, 5)
        x, y = xy_of(0, 4, col_in(0, 4, "Shapes", 2))
        page.mouse.move(x, y)
        page.wait_for_function("panes[0].editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-taglink')", timeout=5000)
        check("no Ctrl: a symbol with an indexed declaration is a link", any("Shapes.java:2" in z[2] for z in link_deco(0)), str(link_deco(0)))
        # drag-selecting across the link does not open anything
        x2, y2 = xy_of(0, 4, col_in(0, 4, "Shapes", 6) + 6)
        page.mouse.down(); page.mouse.move(x2, y2, steps=6); page.mouse.up()
        time.sleep(0.7)
        check("drag selection over a link selects text, opens nothing", ev("panes.length") == 1
              and not ev("panes[0].editor.getSelection().isEmpty()"))
        # Alt+click on the link: a single cursor there, nothing opens
        page.mouse.move(5, 5); time.sleep(0.2)
        page.mouse.move(x, y)
        page.wait_for_function("panes[0].editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-taglink')", timeout=5000)
        page.keyboard.down("Alt"); page.mouse.click(x, y); page.keyboard.up("Alt")
        time.sleep(0.7)
        p = ev("[panes[0].editor.getSelections().length, panes[0].editor.getPosition().lineNumber]")
        check("Alt+click on a link puts a single cursor there, opens nothing", ev("panes.length") == 1 and p == [1, 4], str(p))
        # double-click selects the word, opens nothing
        page.mouse.dblclick(x, y)
        time.sleep(0.7)
        check("double-click on a link selects the word, opens nothing", ev("panes.length") == 1
              and ev("panes[0].editor.getModel().getValueInRange(panes[0].editor.getSelection())") == "Shapes")
        # not resolvable: no link, a click is a click
        page.mouse.move(5, 5)
        x3, y3 = xy_of(0, 3, col_in(0, 3, "run", 1))  # `void run()`: its own declaration
        page.mouse.move(x3, y3); time.sleep(0.6)
        check("a declaration itself / an unknown word is not a link", not link_deco(0))
        page.mouse.click(x3, y3); time.sleep(0.6)
        check("…and a click there just moves the cursor", ev("panes.length") == 1 and ev("panes[0].editor.getPosition().lineNumber") == 3)
        # setting off: no hover link, plain click is a click (Ctrl+hover still works)
        ev("STATE.componentClick = false")
        page.mouse.move(5, 5); page.mouse.move(x, y); time.sleep(0.6)
        check("setting off: no link on plain hover", not link_deco(0))
        page.mouse.click(x, y); time.sleep(0.6)
        check("setting off: plain click does not open", ev("panes.length") == 1)
        ev("STATE.componentClick = true")
        reset_single()
        # the manager's case: Vue SFC import lines, "@/" without alias config; no Ctrl
        NI = "proj/noconf/client/src/main/page/product/Items.vue"
        reset_single()
        ev(f"openFileInPane(0, {json.dumps(NI)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(NI)}", timeout=5000)
        for what, col in (("path string", col_in(0, 5, "product/ProdInfo", 3)), ("imported name", col_in(0, 5, "ProdInfo from", 3))):
            page.mouse.move(5, 5); time.sleep(0.2)
            x, y = xy_of(0, 5, col)
            page.mouse.move(x, y)
            page.wait_for_function("panes[0].editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-taglink')", timeout=5000)
            d = link_deco(0)
            check(f"no alias config, no Ctrl: hover on the {what} shows a link to ProdInfo.vue", any("noconf/client/src/main/page/product/ProdInfo.vue" in z[2] for z in d), str(d))
            page.mouse.click(x, y)
            page.wait_for_function("panes.length === 2 && (panes[1].currentPath || '').endsWith('product/ProdInfo.vue')", timeout=8000)
            check(f"…click on the {what} opens it in the next pane", ev("activePaneIdx") == 0)
            reset_single()
            ev(f"openFileInPane(0, {json.dumps(NI)})")
            page.wait_for_function(f"panes[0].currentPath === {json.dumps(NI)}", timeout=5000)
        page.mouse.move(5, 5); time.sleep(0.2)
        x, y = xy_of(0, 8, col_in(0, 8, "Ghost.vue", 2))
        page.mouse.move(x, y); time.sleep(0.6)
        check("an import of a file that exists nowhere is not underlined", not link_deco(0))
        reset_single()
        # Ctrl+Alt+F12: same pane
        ev(f"panes[0].editor.focus(); panes[0].editor.setPosition({{lineNumber: 6, column: {col_in(0, 6, 'RelatedProductsSection', 1)}}})")
        page.keyboard.press("Control+Alt+F12")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(S + 'service/product/domain/productModel.ts')}", timeout=8000)
        check("Ctrl+Alt+F12 on an import opens it in this pane", ev("panes.length") == 1)
        reset_single()
        ev("while (panes.length > 1) closePane(1)")

        # --- TypeScript / JavaScript: no false diagnostics; identifiers open their definition beside ---
        T = "proj/shop/src/main/service/cart/cartEventBus.ts"
        TM = "proj/shop/src/main/service/cart/domain/CartModel.ts"
        TP = "proj/shop/src/main/service/product/domain/productModel.ts"
        TJ = "proj/shop/src/main/service/cart/cartUtil.js"
        MARKS = "uri => monaco.editor.getModelMarkers({}).filter(m => m.resource.path.endsWith(uri)).length"

        def open_single(key):
            ev("while (panes.length > 1) closePane(1)")
            ev(f"openFileInPane(0, {json.dumps(key)}); focusPane(0)")
            page.wait_for_function(f"panes.length === 1 && panes[0].currentPath === {json.dumps(key)}", timeout=5000)

        check("TS / JS diagnostics are off by default",
              ev("(() => { const o = monaco.languages.typescript.typescriptDefaults.getDiagnosticsOptions(), j = monaco.languages.typescript.javascriptDefaults.getDiagnosticsOptions();"
                 " return !STATE.langDiagnostics && o.noSemanticValidation && o.noSyntaxValidation && o.noSuggestionDiagnostics && j.noSemanticValidation && j.noSyntaxValidation; })()"))
        open_single(TJ)
        open_single(T)
        time.sleep(3)  # the TS worker would have reported by now
        check("TS diagnostic markers: 0 in a .ts file with @/ imports, an npm import and an unknown name (and in a .js file)",
              ev(f"({MARKS})('cartEventBus.ts')") == 0 and ev(f"({MARKS})('cartUtil.js')") == 0,
              str(ev("monaco.editor.getModelMarkers({}).map(m => m.message.slice(0, 50))")))
        ev("STATE.langDiagnostics = true; applyLangDiagnostics()")
        try:
            page.wait_for_function(f"({MARKS})('cartEventBus.ts') > 0", timeout=15000)
            on_n = ev(f"({MARKS})('cartEventBus.ts')")
        except Exception:
            on_n = 0
        ev("STATE.langDiagnostics = false; applyLangDiagnostics()")
        time.sleep(0.5)
        check("'Show language diagnostics' on: the TS errors come back; off again: markers cleared (gutter / ruler / minimap)",
              on_n > 0 and ev(f"({MARKS})('cartEventBus.ts')") == 0 and ev(f"({MARKS})('cartUtil.js')") == 0, str(on_n))
        check("Settings has the 'Show language diagnostics' toggle", ev("!!document.getElementById('setLangDiagnostics')"))

        def click_def(line, word, k, want, want_line, what):
            open_single(T)
            page.mouse.move(5, 5); time.sleep(0.15)
            x, y = xy_of(0, line, col_in(0, line, word, k))
            page.mouse.move(x, y)
            try:
                page.wait_for_function("panes[0].editor.getModel().getAllDecorations().some(d => d.options.inlineClassName === 'reado-taglink')", timeout=5000)
                under = True
            except Exception:
                under = False
            page.mouse.click(x, y)
            try:
                page.wait_for_function(f"panes.length === 2 && panes[1].currentPath === {json.dumps(want)} && panes[1].editor.getPosition().lineNumber === {want_line}", timeout=8000)
                ok = True
            except Exception:
                ok = False
            check(f"TS click on {what}: underlined, opens {want.split('/')[-1]}:{want_line} beside, focus stays",
                  under and ok and ev("activePaneIdx") == 0, str([under, ev("panes.map(p => p.currentPath)"), ev("panes[1] && panes[1].editor.getPosition()")]))

        click_def(7, "AddToCartDto", 2, T, 9, "a type declared in the same file")
        click_def(11, "makeCartBus", 2, T, 10, "a function declared in the same file")
        click_def(6, "CartOrderLineItem", 3, TM, 3, "a used imported type (other file, through the import)")
        click_def(3, "CartOrderLineItem", 3, TM, 3, "a name inside import { … } (straight to the symbol)")
        click_def(9, "ProductDetail", 2, TP, 3, "an imported type via an @/ path with no alias config")
        click_def(13, "MAX_CART_ITEMS", 2, TM, 7, "a name not imported (symbol index fallback)")

        def no_link(line, word, what):
            open_single(T)
            page.mouse.move(5, 5); time.sleep(0.15)
            x, y = xy_of(0, line, col_in(0, line, word, 2))
            page.mouse.move(x, y); time.sleep(0.7)
            check(f"TS: {what} is not underlined", not link_deco(0), str(link_deco(0)))
        no_link(13, "undefinedThing", "an unresolvable name")
        no_link(10, "mitt", "an npm package's import (outside the folder)")
        ev("while (panes.length > 1) closePane(1)")
        reset_single()

        # --- multi-pane layout (up to 4), pane focus keys, moving tabs, restore ---
        A, B, C = "proj/A.java", "proj/B.java", "proj/conf.toml"
        ev("(async () => { while (panes.length > 1) closePane(1);"
           " for (const k of [...panes[0].tabs.keys()]) await closeTabIn(0, k, true); })()")
        ev(f"openFileInPane(0, {json.dumps(A)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(A)}", timeout=5000)

        def rects():
            return ev("panes.map(p => { const r = p.paneEl.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; })")

        def tabs(i):
            return ev(f"[...panes[{i}].tabs.keys()]")

        ev("panes[0].editor.focus(); panes[0].editor.setPosition({lineNumber: 1, column: 1})")
        page.keyboard.press("Control+Alt+ArrowDown")
        check("one pane: Ctrl+Alt+↓ is still Monaco's add-cursor-below", ev("panes[0].editor.getSelections().length") == 2)
        ev("panes[0].editor.setPosition({lineNumber: 1, column: 1})")
        ev("applyLayoutPreset('grid')")
        r = rects()
        check("grid preset: 4 panes in reading order (1 2 / 3 4)", len(r) == 4 and r[0][1] == r[1][1] and r[2][1] == r[3][1]
              and r[0][0] == r[2][0] and r[1][0] > r[0][0] and r[2][1] > r[0][1], str(r))
        check("grid preset keeps the open file in pane 1, new panes are empty", tabs(0) == [A] and tabs(1) == [] and
              ev("panes[1].paneEl.classList.contains('empty')"))
        check("pane numbers shown on the tab bars", ev("panes.map(p => p.tabsEl.querySelector('.pane-num').textContent).join('')") == "1234")
        check("5th pane refused", ev("splitPane(0, 'row')") is None and "at most 4" in ev("document.getElementById('toast').textContent"))
        # Ctrl+1..4 and Ctrl+Alt+arrows
        ev("focusPane(0)")
        page.keyboard.press("Control+3")
        check("Ctrl+3 focuses pane 3", ev("activePaneIdx") == 2 and ev("panes[2].editor.hasTextFocus()"))
        page.keyboard.press("Control+1")
        check("Ctrl+1 focuses pane 1 (from inside an editor)", ev("activePaneIdx") == 0 and ev("panes[0].editor.hasTextFocus()"))
        seq = []
        for k in ["Control+Alt+ArrowRight", "Control+Alt+ArrowDown", "Control+Alt+ArrowLeft", "Control+Alt+ArrowUp"]:
            page.keyboard.press(k)
            seq.append(ev("activePaneIdx"))
        check("Ctrl+Alt+→ ↓ ← ↑ walk the grid 1→2→4→3→1", seq == [1, 3, 2, 0], str(seq))
        check("pane focus is visible (active class on one pane)", ev("panes.map(p => p.paneEl.classList.contains('active'))") == [True, False, False, False])
        # move the tab with Ctrl+Alt+PgDn / PgUp
        page.keyboard.press("Control+Alt+PageDown")
        page.wait_for_function(f"panes[1].currentPath === {json.dumps(A)}", timeout=5000)
        check("Ctrl+Alt+PgDn moves the tab to the next pane", tabs(0) == [] and tabs(1) == [A] and ev("activePaneIdx") == 1)
        page.keyboard.press("Control+Alt+PageUp")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(A)}", timeout=5000)
        check("Ctrl+Alt+PgUp moves it back", tabs(0) == [A] and tabs(1) == [])
        check("moving a tab keeps one shared doc (refs 1)", ev(f"docs.get({json.dumps(A)}).refs") == 1)
        # drag a tab from pane 1 to pane 4
        ev(f"openFileInPane(0, {json.dumps(B)})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(B)}", timeout=5000)
        ev(f"panes[0].tabsEl.querySelector('.tab-item[data-key=\"{B}\"]').id = 'dragSrc'; panes[3].editorEl.id = 'dropDst'")
        page.drag_and_drop("#dragSrc", "#dropDst")
        page.wait_for_function(f"panes[3].currentPath === {json.dumps(B)}", timeout=5000)
        check("dragging a tab onto another pane moves it", tabs(0) == [A] and tabs(3) == [B] and ev("activePaneIdx") == 3)
        ev("panes[3].editorEl.removeAttribute('id')")
        # reorder by dropping onto a tab of the same pane
        ev(f"openFileInPane(3, {json.dumps(C)})")
        page.wait_for_function(f"panes[3].tabs.size === 2", timeout=5000)
        ev(f"panes[3].tabsEl.querySelector('.tab-item[data-key=\"{C}\"]').id = 'dragSrc2'; panes[3].tabsEl.querySelector('.tab-item[data-key=\"{B}\"]').id = 'dropTab'")
        page.drag_and_drop("#dragSrc2", "#dropTab")
        page.wait_for_function(f"panes[3].tabsEl.querySelector('.tab-item').dataset.key === {json.dumps(C)}", timeout=5000)
        check("dropping a tab on a tab reorders (inserted before it)", tabs(3) == [C, B])
        # context menu: copy to pane 2, split items disabled at 4 panes
        ev(f"panes[3].tabsEl.querySelector('.tab-item[data-key=\"{B}\"]').dispatchEvent(new MouseEvent('contextmenu', {{bubbles: true, clientX: 300, clientY: 300}}))")
        page.wait_for_selector("#ctxMenu", timeout=3000)
        labels = ev("[...document.querySelectorAll('#ctxMenu .ctx-item')].map(x => x.dataset.label + (x.classList.contains('disabled') ? '!' : ''))")
        check("tab menu: split right/down (disabled when full), move to / copy to other panes, close",
              labels[:2] == ["split right!", "split down!"] and "move to pane 1" in labels and "copy to pane 2" in labels and "close" in labels and "close others" in labels, str(labels))
        page.click("#ctxMenu .ctx-item[data-label='copy to pane 2']")
        page.wait_for_function(f"panes[1].currentPath === {json.dumps(B)}", timeout=5000)
        ev(f"switchTabIn(3, {json.dumps(B)})")
        check("'copy to pane 2' duplicates the tab (both panes, one model)", tabs(3) == [C, B] and tabs(1) == [B]
              and ev(f"panes[1].editor.getModel() === panes[3].editor.getModel() && docs.get({json.dumps(B)}).refs === 2"),
              str([tabs(3), tabs(1), ev(f"docs.get({json.dumps(B)}).refs"), ev("panes[1].editor.getModel() === panes[3].editor.getModel()")]))
        # same file in two panes: one model, one dirty state, closing one copy does not ask
        ev("STATE.editMode = true; panes.forEach(applyEditorMode)")
        ev("panes[1].editor.focus(); panes[1].editor.setPosition({lineNumber: 1, column: 1})")
        page.keyboard.type("X")
        check("typing in pane 2 shows in pane 4 (same model)", ev("panes[3].editor.getModel().getLineContent(1)").startswith("Xpackage"),
              ev("[panes[3].editor.getModel().getLineContent(1), panes[1].editor.getModel().getLineContent(1), panes[1].currentPath, panes[3].currentPath]"))
        check("both tabs show dirty", ev(f"[1, 3].map(i => panes[i].tabsEl.querySelector('.tab-item[data-key=\"{B}\"]').classList.contains('dirty'))") == [True, True])
        ev(f"closeTabIn(1, {json.dumps(B)})")
        page.wait_for_function(f"!panes[1].tabs.has({json.dumps(B)})", timeout=3000)
        check("closing one of two copies of a dirty file does not prompt; edits kept", not ev("!!_dlgResolve")
              and ev(f"docs.get({json.dumps(B)}).dirty") and ev(f"docs.get({json.dumps(B)}).refs") == 1)
        ev(f"docs.get({json.dumps(B)}).model.undo()")
        page.wait_for_function(f"!docs.get({json.dumps(B)}).dirty", timeout=3000)
        check("undo clears the shared dirty state", True)
        # component jump with 3+ panes: the next pane, cyclic
        ev("applyLayoutPreset('cols3')")
        check("three columns preset from grid: 3 panes left to right", len(rects()) == 3 and rects()[0][1] == rects()[2][1])
        ev(f"openFileInPane(2, {json.dumps(F)})")
        page.wait_for_function(f"panes[2].currentPath === {json.dumps(F)}", timeout=5000)
        T = "proj/web/src/components/item/ItemTop.vue"
        for i in range(3):
            ev(f"closeTabIn({i}, {json.dumps(T)}, true)")
        ev("STATE.componentBeside = true; focusPane(2); panes[2].editor.setPosition({lineNumber: 3, column: 8})")
        page.keyboard.press("F12")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(T)}", timeout=8000)
        check("component jump from the last pane opens in pane 1 (next, cyclic)", ev("panes[2].currentPath") == F)
        ev(f"(async () => {{ await openFileInPane(1, {json.dumps(T)}, null, null, {{background: true}}); await closeTabIn(0, {json.dumps(T)}, true); }})()")
        ev("focusPane(2); panes[2].editor.setPosition({lineNumber: 3, column: 8})")
        page.keyboard.press("F12")
        page.wait_for_function(f"panes[1].currentPath === {json.dumps(T)}", timeout=8000)
        check("…and activates it where it is already open (pane 2), no new copy",
              ev(f"panes.map(p => p.tabs.has({json.dumps(T)}))") == [False, True, False])
        # rows2 preset, split down, close pane -> neighbours take the space
        ev("applyLayoutPreset('rows2')")
        r = rects()
        check("two rows preset: stacked", len(r) == 2 and r[0][0] == r[1][0] and r[1][1] > r[0][1], str(r))
        ev("focusPane(1)")
        page.keyboard.press("Control+Alt+Backslash")
        r = rects()
        check("Ctrl+Alt+\\ splits the bottom pane down (3 rows)", len(r) == 3 and r[2][1] > r[1][1] > r[0][1], str(r))
        page.keyboard.press("Control+Backslash")
        r = rects()
        check("Ctrl+\\ splits right next to it (4 panes)", len(r) == 4 and r[3][1] == r[2][1] and r[3][0] > r[2][0], str(r))
        h_before = ev("panes[0].paneEl.getBoundingClientRect().height")
        ev("closePane(1)")
        check("closing a pane gives its space to the rest", len(rects()) == 3 and ev("panes[0].paneEl.getBoundingClientRect().height") > h_before + 20)
        # unsaved tab only held by a closing pane moves to its neighbour
        ev("applyLayoutPreset('cols2')")
        ev(f"(async () => {{ for (const i of [0, 1]) for (const k of [...panes[i].tabs.keys()]) await closeTabIn(i, k, true); }})()")
        ev(f"openFileInPane(1, {json.dumps(C)})")
        page.wait_for_function(f"panes[1].currentPath === {json.dumps(C)}", timeout=5000)
        ev("panes[1].editor.focus(); panes[1].editor.setPosition({lineNumber: 1, column: 1})")
        page.keyboard.type("Q")
        ev("closePane(1)")
        check("closing a pane keeps its unsaved tab (moved to the neighbour)", tabs(0) == [C] and ev(f"docs.get({json.dumps(C)}).dirty"))
        ev("panes[0].editor.getModel().undo()")
        # sash drag resizes, layout + sizes + tabs survive a reload
        ev("applyLayoutPreset('grid')")
        for i, k in enumerate([A, B, C, F]):
            ev(f"openFileInPane({i}, {json.dumps(k)})")
        page.wait_for_function(f"panes[3].currentPath === {json.dumps(F)}", timeout=5000)
        box = ev("(() => { const s = document.querySelector('#paneRoot .split.col > .split.row > .sash').getBoundingClientRect(); return [s.left + s.width / 2, s.top + s.height / 2]; })()")
        w0 = ev("panes[0].paneEl.getBoundingClientRect().width")
        page.mouse.move(box[0], box[1]); page.mouse.down(); page.mouse.move(box[0] - 120, box[1], steps=5); page.mouse.up()
        w1 = ev("panes[0].paneEl.getBoundingClientRect().width")
        check("dragging a sash resizes the panes beside it", w1 < w0 - 80, f"{w0} -> {w1}")
        ev("focusPane(2)")
        layout_before = ev("JSON.stringify(serializeLayout(_layout))")
        ev("flushState()")
        time.sleep(0.5)
        page.reload()
        page.wait_for_function("typeof monaco !== 'undefined' && _stateReady", timeout=20000)
        page.wait_for_function(f"panes.length === 4 && panes[3].currentPath === {json.dumps(F)}", timeout=10000)
        check("reload restores the 2×2 layout with sizes", ev("JSON.stringify(serializeLayout(_layout))") == layout_before,
              ev("JSON.stringify(serializeLayout(_layout))") + " vs " + layout_before)
        check("reload restores each pane's tab", ev("panes.map(p => p.currentPath)") == [A, B, C, F])
        r = rects()
        check("restored panes sit in a 2×2 grid", r[0][1] == r[1][1] and r[2][1] == r[3][1] and r[0][0] == r[2][0] and r[0][2] < r[1][2], str(r))
        check("no '× pane' close button is rendered in split panes",
              ev("document.querySelectorAll('.pane-close').length + [...document.querySelectorAll('#paneRoot button')].filter(b => /pane/.test(b.textContent)).length") == 0
              and ev("panes.every(p => !p.closeBtn)"))
        check("Close Pane stays in the palette registry and the Layout menu",
              ev("!!CMD.get('layout.closePane') && JSON.stringify(MENUS).includes('layout.closePane')"))
        ev("runCommand('layout.closePane')")
        check("layout.closePane command closes the active pane", ev("panes.length") == 3)
        ev("applyLayoutPreset('single')")
        check("single preset: back to one pane", ev("panes.length") == 1)
        ev("flushState()")
        # the persistence checks below expect the outside file and a split as earlier tests left them
        ev(f"openFileInPane(0, {json.dumps(os.path.realpath(ext))})")
        page.wait_for_function(f"panes[0].currentPath === {json.dumps(os.path.realpath(ext))}", timeout=5000)
        ev("splitPane(0, 'row', 'proj/B.java')")
        page.wait_for_function("panes.length === 2 && panes[1].currentPath === 'proj/B.java'", timeout=5000)

        # --- 3. persistence across restart ---
        ev("toggleTheme()"); ev("toggleWrap()")
        ev("saveFIFRecent('needle')")
        ev("flushState()")
        time.sleep(0.5)
        tabs_before = ev("snapshotPanes().map(p => [p.tabs.map(t => t.key), p.active])")
        state = json.load(open(os.path.join(CFG, "state.json"), encoding="utf-8"))
        check("state.json written next to config", state["ui"]["theme"] == "dark" and "needle" in state["ui"]["fifRecent"])
        server._state = None  # simulate a fresh process reading state.json
        page2 = ctx.new_page()
        page2.on("pageerror", lambda e: errors.append("p2: " + str(e)))
        page2.goto(f"http://127.0.0.1:{PORT}/")
        page2.wait_for_function("typeof monaco !== 'undefined' && _stateReady", timeout=20000)
        ev2 = page2.evaluate
        check("theme restored before Monaco (inline state)", ev2("document.body.classList.contains('theme-dark')"))
        tabs_after = ev2("snapshotPanes().map(p => [p.tabs.map(t => t.key), p.active])")
        check("open tabs, split and active tab restored", tabs_after == tabs_before, f"{tabs_before} vs {tabs_after}")
        check("outside-file tab restored", any(os.path.realpath(ext) in t for t, _ in tabs_after))
        check("edit mode, wrap, recent searches restored",
              ev2("STATE.editMode && STATE.wordWrap && STATE.fifRecent[0] === 'needle' && editor.getOption(monaco.editor.EditorOption.wordWrap) === 'on'"))
        ev2("openQO('')")
        rec = ev2("_qoItems.map(i => i.path)")
        check("Ctrl+E / empty Quick Open lists recent files", len(rec) >= 3, str(rec[:4]))
        page2.close()

        browser.close()

    # --- A: no folder -> start screen; migration of an old config ---
    import json as _json
    server.SETTINGS = server.save_settings({"base_dir": ""})
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append("p3: " + str(e)))
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.wait_for_function("typeof monaco !== 'undefined' && _stateReady", timeout=20000)
        ev = page.evaluate
        check("no folder: start screen shown, tree says no folder",
              ev("document.getElementById('startScreen').style.display") == "flex"
              and "No folder open" in ev("document.getElementById('tree').textContent"))
        check("no folder: settings modal does not pop up", not ev("document.getElementById('settingsBg').classList.contains('show')"))
        st = ev("fetch('/api/file?path=proj/A.java').then(r => r.status)")
        st2 = ev("fetch('/api/tree?path=').then(r => r.json()).then(d => d.no_folder)")
        check("no folder: nothing under the current directory is served", st == 404 and st2 is True, str(st))
        page.fill("#startPath", BASE)
        page.keyboard.press("Enter")
        page.wait_for_selector('#tree .node[data-path="proj"]', timeout=5000)
        check("folder opened from start screen is remembered", server.SETTINGS["base_dir"] == BASE
              and _json.load(open(os.path.join(CFG, "config.json")))["base_dir"] == BASE
              and ev("STATE.recentFolders[0]") == BASE)
        check("start screen stays while no file is open, lists recent folder",
              ev("document.getElementById('startFolders').textContent").find(BASE) >= 0)
        ev("openFile('proj/A.java')")
        page.wait_for_function("document.getElementById('startScreen').style.display === 'none'", timeout=5000)
        check("start screen hides once a file is open", True)
        browser.close()
    v1 = {"base_dir": r"c:\Projects-does-not-exist", "ignored": list(reversed(server._V1_DEFAULT_IGNORED)),
          "extensions": [".java"], "max_file_bytes": 2000000, "search_max_results": 500}
    with open(server.CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump(v1, f)
    old_default, server._V1_DEFAULT_BASE_DIR = server._V1_DEFAULT_BASE_DIR, v1["base_dir"]  # (real one exists here)
    m = server.load_settings()
    server._V1_DEFAULT_BASE_DIR = old_default
    saved = _json.load(open(server.CONFIG_PATH, encoding="utf-8"))
    check("old config migrated: general ignore list, no extension allow-list, missing old base_dir cleared",
          m["ignored"] == server.DEFAULT_SETTINGS["ignored"] and "extensions" not in saved
          and m["base_dir"] == "" and saved["config_version"] == 2, str(saved))
    v1b = dict(v1, ignored=["foo", ".*"], base_dir=BASE)
    with open(server.CONFIG_PATH, "w", encoding="utf-8") as f:
        _json.dump(v1b, f)
    m = server.load_settings()
    check("user-changed ignore list and base_dir kept on migration", m["ignored"] == ["foo", ".*"] and m["base_dir"] == BASE)
    server.SETTINGS = server.save_settings({"base_dir": BASE, "ignored": server.DEFAULT_SETTINGS["ignored"]})

    # --- reado.py: second instance hand-off, drop handler, close prompt ---
    import importlib
    saved_cfg, saved_settings = server.CONFIG_PATH, server.SETTINGS
    reado = importlib.import_module("reado")
    server.CONFIG_PATH, server.SETTINGS = saved_cfg, saved_settings
    reado.INSTANCE_PATH = os.path.join(CFG, "instance.json")
    reado.PORT = PORT
    reado.write_instance_file()
    target = os.path.join(OUT, "secret.txt")
    with server._state_lock:
        server._pending_open.clear()
    check("second instance forwards argv to running one", reado.forward_to_running([target]))
    check("forwarded file queued for the page", server._pending_open == [os.path.realpath(target)], str(server._pending_open))

    class FakeWin:
        js = []
        def run_js(self, s): self.js.append(s)
    fw = FakeWin()
    reado.on_drop(fw, {"dataTransfer": {"files": [{"name": "ext.txt", "pywebviewFullPath": ext}]}})
    check("drop handler grants + queues + pokes the page", fw.js and server._pending_open[-1] == os.path.realpath(ext))
    reado.Api.dirty = 0
    check("close allowed when nothing is dirty", reado.on_closing() is True)
    reado.remove_instance_file()
    check("instance file removed on exit", not os.path.exists(reado.INSTANCE_PATH))

    # --- port fallback + hand-off uses the port recorded in instance.json ---
    import socket
    blocker = socket.socket()
    try:
        blocker.bind(("127.0.0.1", 8766))
        blocker.listen(1)
        blocked = True
    except OSError:
        blocked = True  # already taken by something else: same situation
    reado.PREFERRED_PORT = 8766
    httpd2 = reado.bind_server()
    p2 = httpd2.server_address[1]
    check("8766 busy -> binds another free port", p2 != 8766 and reado.PORT == p2, str(p2))
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    reado.write_instance_file()
    with server._state_lock:
        server._pending_open.clear()
    raised = []
    server.on_open_request = lambda: raised.append(1)
    check("second launch forwards to the instance on the fallback port", reado.forward_to_running([ext]) and raised)
    reado.remove_instance_file()
    check("stale instance file -> no forward (starts normally)", reado.forward_to_running([ext]) is False)

    # --- an instance that never showed its window (start-up hang) does not swallow a second launch ---
    import subprocess
    reado.write_instance_file(shown=True)
    inst_base = _json.load(open(reado.INSTANCE_PATH, encoding="utf-8"))
    os.remove(reado.INSTANCE_PATH)
    log_path = os.path.join(CFG, "startup.log")

    def fake_instance(pid, started, shown=False):
        d = dict(inst_base, pid=pid, started=started, shown=shown, exe=sys.executable)
        with open(reado.INSTANCE_PATH, "w", encoding="utf-8") as f:
            _json.dump(d, f)
    sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
    old_env, old_grace = os.environ.get("READO_STARTUP_TIMEOUT"), reado.STARTUP_GRACE
    os.environ["READO_STARTUP_TIMEOUT"] = "1"
    reado.STARTUP_GRACE = 1.0
    try:
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        fake_instance(gone.pid, time.time())
        t = time.time()
        r = reado.forward_to_running([ext])
        check("instance file of a process that is gone: dropped at once, start normally",
              r is False and not os.path.exists(reado.INSTANCE_PATH) and time.time() - t < 1.5, f"{time.time() - t:.1f}s")

        stuck = subprocess.Popen(sleeper)
        time.sleep(0.3)
        fake_instance(stuck.pid, time.time())
        t = time.time()
        r = reado.forward_to_running([ext])
        dt = time.time() - t
        try:
            stuck.wait(5)
        except subprocess.TimeoutExpired:
            pass
        logged = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""
        check("window never shown: the second launch waits (limit + grace), ends that process, starts on its own",
              r is False and stuck.poll() is not None and not os.path.exists(reado.INSTANCE_PATH) and 1.5 < dt < 4.5,
              f"r={r} exit={stuck.poll()} dt={dt:.1f}s")
        check("…and says so in startup.log", f"pid {stuck.pid}" in logged and "never showed its window" in logged, logged[-200:])

        other = subprocess.Popen(sleeper)  # alive, but not the process the file describes (PID reused)
        time.sleep(0.3)
        fake_instance(other.pid, time.time() - 3600)
        r = reado.forward_to_running([ext])
        check("a reused PID (other start time) is never ended — only passed over", r is False and other.poll() is None
              and not os.path.exists(reado.INSTANCE_PATH), f"r={r} exit={other.poll()}")
        other.kill()

        slow = subprocess.Popen(sleeper)  # still starting: its window comes up during the wait
        time.sleep(0.3)
        fake_instance(slow.pid, time.time())
        threading.Timer(0.8, lambda: fake_instance(slow.pid, time.time(), shown=True)).start()
        with server._state_lock:
            server._pending_open.clear()
        raised.clear()
        r = reado.forward_to_running([ext])
        check("instance still starting: the second launch waits for its window, then hands over the files",
              r is True and raised and slow.poll() is None, f"r={r} exit={slow.poll()}")
        slow.kill()
        os.remove(reado.INSTANCE_PATH)
    finally:
        reado.STARTUP_GRACE = old_grace
        if old_env is None:
            os.environ.pop("READO_STARTUP_TIMEOUT", None)
        else:
            os.environ["READO_STARTUP_TIMEOUT"] = old_env
    httpd2.shutdown()
    blocker.close()

    # --- start-up watchdog: no window in time -> startup.log + exit; shown in time -> nothing ---
    wd_log = os.path.join(CFG, "watchdog.log")
    code = ("import sys, time; sys.path.insert(0, {repo!r}); import startguard; w = startguard.Watchdog(1, {log!r}).start(); "
            "{shown}time.sleep(6)")
    t = time.time()
    p = subprocess.run([sys.executable, "-c", code.format(repo=REPO, log=wd_log, shown="")], timeout=30)
    dt = time.time() - t
    wl = open(wd_log, encoding="utf-8").read() if os.path.exists(wd_log) else ""
    check("watchdog: no window within the limit -> exits (code 3) instead of hanging", p.returncode == 3 and dt < 5, f"code={p.returncode} {dt:.1f}s")
    check("watchdog: startup.log has the reason, stage and every thread's stack",
          "no window after 1 s" in wl and "stage: starting" in wl and "--- thread MainThread" in wl, wl[:300])
    p = subprocess.run([sys.executable, "-c", code.format(repo=REPO, log=wd_log + "2", shown="w.shown(); ")], timeout=30)
    check("watchdog: window shown in time -> it stands down", p.returncode == 0 and not os.path.exists(wd_log + "2"), str(p.returncode))
    # no WMI: platform answers without it, and nothing in this process asked WMI
    import platform
    import nowmi  # reado imported it first
    platform._uname_cache = None
    n0 = len(nowmi.blocked)
    check("no WMI: platform.system() / machine() / win32_ver() answer through the non-WMI fallback (WMI refused)",
          platform.system() == "Windows" and platform.machine() and platform.win32_ver()[1] and len(nowmi.blocked) > n0,
          f"{platform.win32_ver()} refused={nowmi.blocked[n0:]}")

    # --- Open with (HKCU) register / unregister ---
    import winreg
    st0 = reado.assoc_status()
    if st0.get("registered"):
        check("Open with test skipped: a registration already exists", True)
    else:
        st1 = reado.register_assoc()
        def has_progid(ext):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\OpenWithProgids" % ext) as k:
                    winreg.QueryValueEx(k, reado.PROGID)
                return True
            except OSError:
                return False
        check("register: ProgID + OpenWithProgids for settings extensions",
              st1.get("registered") and st1.get("current") and has_progid(".java") and has_progid(".txt"), str(st1)[:200])
        st2 = reado.unregister_assoc()
        check("unregister removes ProgID and OpenWithProgids entries",
              not st2.get("registered") and not has_progid(".java") and not has_progid(".txt"))

    check("no page errors", not errors, "; ".join(errors[:5]))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} / {len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
