/* OpsMate 前端入口（零构建）：Vue3 全局构建 + hash 路由骨架。Phase 0：5 导航空壳。 */
"use strict";

/* ============ 通用工具（后续各 Phase 页面共用） ============ */

/**
 * 统一 fetch 封装：超时控制 + JSON 解析 + 错误 toast。
 * @param {string} url 请求地址
 * @param {RequestInit} [options] fetch 配置（method/headers/body）
 * @param {number} [timeoutMs=30000] 超时毫秒数
 * @returns {Promise<any>} 解析后的 JSON；失败抛错并 toast
 */
async function apiFetch(url, options, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, Object.assign({}, options, { signal: controller.signal }));
    if (!resp.ok) {
      let detail = "";
      try { detail = (await resp.json()).detail || ""; } catch (e) { /* 响应体非 JSON 时忽略 */ }
      throw new Error("HTTP " + resp.status + (detail ? "：" + detail : ""));
    }
    return await resp.json();
  } catch (err) {
    if (err.name === "AbortError") {
      showToast("请求超时，请检查后端服务", "err");
    } else {
      showToast(String(err.message || err), "err");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 右上角 toast 提示（成功绿 / 失败红，3s 自动消失）。
 * @param {string} message 提示文案
 * @param {"ok"|"err"} [type="ok"] 提示类型
 */
function showToast(message, type = "ok") {
  let wrap = document.querySelector(".toast-wrap");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.className = "toast-wrap";
    document.body.appendChild(wrap);
  }
  const toast = document.createElement("div");
  toast.className = "toast " + (type === "err" ? "err" : "ok");
  toast.textContent = message;
  wrap.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

/* ============ hash 路由与应用骨架 ============ */

/** 左侧边栏 5 个导航项（契约 §7，顺序固定） */
const NAV_ITEMS = [
  { hash: "#/commands", page: "commands", label: "指令速查" },
  { hash: "#/kb",       page: "kb",       label: "配置速查" },
  { hash: "#/codegen",  page: "codegen",  label: "脚本工坊" },
  { hash: "#/logs",     page: "logs",     label: "日志中心" },
  { hash: "#/settings",  page: "settings", label: "设置" },
];

/** 各模块施工占位文案（Phase 1-6 逐个替换为真实视图） */
const PLACEHOLDER = {
  commands: "指令速查：600+ 中文 Linux 命令离线检索（Phase 1 施工）",
  kb: "配置速查：nginx / zabbix 启停命令与配置参数分 Tab 查询（Phase 2 施工）",
  codegen: "脚本工坊：自然语言生成带中文注释的 bash 脚本（Phase 4 施工）",
  logs: "日志中心：上传 / 粘贴日志，过滤、着色、统计、导出与 AI 分析（Phase 5-6 施工）",
  settings: "设置：配置大模型接入（Phase 3 施工）",
};

/** 解析当前 hash → 页面名（#/logs/:id 归入 logs 页） */
function parseRoute() {
  const hash = location.hash || "#/commands";
  const name = hash.replace(/^#\//, "").split("/")[0] || "commands";
  return NAV_ITEMS.some((item) => item.page === name) ? name : "commands";
}

const App = {
  data() {
    return { page: parseRoute(), navItems: NAV_ITEMS };
  },
  computed: {
    placeholder() {
      return PLACEHOLDER[this.page] || "";
    },
    activeLabel() {
      const hit = NAV_ITEMS.find((item) => item.page === this.page);
      return hit ? hit.label : "";
    },
  },
  watch: {
    page() {
      /* Phase 0：仅切换空壳占位；后续 Phase 在此挂各页面的数据加载逻辑 */
    },
  },
  created() {
    window.addEventListener("hashchange", () => {
      this.page = parseRoute();
    });
  },
  template: [
    '<div class="layout">',
    '  <aside class="sidebar">',
    '    <div class="logo">OpsMate</div>',
    '    <nav>',
    '      <a v-for="item in navItems" :key="item.hash" :href="item.hash"',
    '         :class="{ active: page === item.page }">{{ item.label }}</a>',
    "    </nav>",
    "  </aside>",
    '  <main class="content">',
    '    <h1 class="ready-title">OpsMate 已就绪</h1>',
    '    <p class="placeholder">当前模块：{{ activeLabel }}</p>',
    '    <p class="placeholder dim">{{ placeholder }}</p>',
    "  </main>",
    "</div>",
  ].join("\n"),
};

Vue.createApp(App).mount("#app");
