/* OpsMate 前端入口（零构建）：Vue3 全局构建 + hash 路由。 */
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
    return {
      page: parseRoute(),
      navItems: NAV_ITEMS,
      commandQuery: "",
      commandItems: [],
      commandTotal: 0,
      commandLoading: false,
      commandDetailLoading: false,
      selectedCommand: null,
      commandSearchTimer: null,
      commandRequestId: 0,
      commandDetailRequestId: 0,
    };
  },
  computed: {
    placeholder() {
      return PLACEHOLDER[this.page] || "";
    },
    activeLabel() {
      const hit = NAV_ITEMS.find((item) => item.page === this.page);
      return hit ? hit.label : "";
    },
    commandHtml() {
      if (!this.selectedCommand) return "";
      const cleaned = this.selectedCommand.markdown.replace(/<!--rehype:[^>]*-->/gi, "");
      return marked.parse(cleaned);
    },
  },
  watch: {
    page(nextPage) {
      if (nextPage === "commands" && this.commandItems.length === 0) {
        this.loadCommands();
      }
    },
  },
  methods: {
    queueCommandSearch() {
      clearTimeout(this.commandSearchTimer);
      this.commandSearchTimer = setTimeout(() => this.loadCommands(), 300);
    },
    async loadCommands() {
      const requestId = ++this.commandRequestId;
      this.commandLoading = true;
      try {
        const query = encodeURIComponent(this.commandQuery.trim());
        const data = await apiFetch("/api/commands?q=" + query + "&limit=2000");
        if (requestId !== this.commandRequestId) return;
        this.commandItems = data.items;
        this.commandTotal = data.total;
        const selectedStillVisible = this.selectedCommand
          && data.items.some((item) => item.name === this.selectedCommand.name);
        if (!selectedStillVisible) {
          this.selectedCommand = null;
          if (data.items.length > 0) await this.selectCommand(data.items[0].name);
        }
      } finally {
        if (requestId === this.commandRequestId) this.commandLoading = false;
      }
    },
    async selectCommand(name) {
      const requestId = ++this.commandDetailRequestId;
      this.commandDetailLoading = true;
      try {
        const data = await apiFetch("/api/commands/" + encodeURIComponent(name));
        if (requestId === this.commandDetailRequestId) this.selectedCommand = data;
      } finally {
        if (requestId === this.commandDetailRequestId) this.commandDetailLoading = false;
      }
    },
    async copyCommandMarkdown() {
      if (!this.selectedCommand) return;
      const markdown = this.selectedCommand.markdown;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(markdown);
        } else {
          const textarea = document.createElement("textarea");
          textarea.value = markdown;
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          const copied = document.execCommand("copy");
          textarea.remove();
          if (!copied) throw new Error("浏览器未允许写入剪贴板");
        }
        showToast("已复制 md 原文");
      } catch (err) {
        showToast("复制失败：" + String(err.message || err), "err");
      }
    },
  },
  created() {
    window.addEventListener("hashchange", () => {
      this.page = parseRoute();
    });
    if (this.page === "commands") this.loadCommands();
  },
  beforeUnmount() {
    clearTimeout(this.commandSearchTimer);
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
    '    <section v-if="page === \'commands\'" class="commands-page">',
    '      <header class="page-header">',
    '        <div><h1>指令速查</h1><p>621 条中文 Linux 命令文档，本地离线检索</p></div>',
    '        <span class="result-count">{{ commandLoading ? "检索中…" : "共 " + commandTotal + " 条" }}</span>',
    '      </header>',
    '      <label class="command-search">',
    '        <span>搜索</span>',
    '        <input v-model="commandQuery" @input="queueCommandSearch" type="search"',
    '               placeholder="输入命令名或中文关键词，例如：磁盘" autocomplete="off">',
    '      </label>',
    '      <div class="command-browser">',
    '        <aside class="command-list" aria-label="命令搜索结果">',
    '          <button v-for="item in commandItems" :key="item.name" type="button"',
    '                  :class="{ active: selectedCommand && selectedCommand.name === item.name }"',
    '                  @click="selectCommand(item.name)">',
    '            <strong>{{ item.name }}</strong><span>{{ item.title }}</span>',
    '          </button>',
    '          <p v-if="!commandLoading && commandItems.length === 0" class="empty-state">未找到匹配命令</p>',
    '        </aside>',
    '        <article class="command-detail">',
    '          <div v-if="selectedCommand" class="command-detail-head">',
    '            <div><h2>{{ selectedCommand.name }}</h2><p>{{ selectedCommand.title }}</p></div>',
    '            <button class="copy-button" type="button" @click="copyCommandMarkdown">复制 md</button>',
    '          </div>',
    '          <p v-if="commandDetailLoading" class="empty-state">正在加载文档…</p>',
    '          <div v-else-if="selectedCommand" class="markdown-body" v-html="commandHtml"></div>',
    '          <p v-else class="empty-state">从左侧选择一个命令查看详情</p>',
    '        </article>',
    '      </div>',
    '    </section>',
    '    <section v-else class="placeholder-page">',
    '      <h1 class="ready-title">OpsMate 已就绪</h1>',
    '      <p class="placeholder">当前模块：{{ activeLabel }}</p>',
    '      <p class="placeholder dim">{{ placeholder }}</p>',
    '    </section>',
    "  </main>",
    "</div>",
  ].join("\n"),
};

Vue.createApp(App).mount("#app");
