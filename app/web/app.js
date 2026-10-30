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
      kbSoftwares: [],
      kbLoading: false,
      kbSelected: null,
      kbDetailLoading: false,
      kbTab: "cli",
      kbExpanded: {},
      kbQuery: "",
      kbSearchItems: null,
      kbSearchLoading: false,
      kbSearchTimer: null,
      settings: { provider: "zhipu", base_url: "", model: "", api_key: "", api_key_set: false },
      settingsLoaded: false,
      settingsBusy: false,
      settingsTesting: false,
      settingsTestResult: "",
      modelProfiles: [],
      selectedProfileId: "current",
      activeProfileId: "current",
      profileName: "原有配置",
      codegenForm: { requirement: "", distro: "", notes: "" },
      codegenBusy: false,
      codegenResult: null,
      codegenHistory: [],
      clarificationAnswers: [],
    };
  },
  computed: {
    profileHasChanges() {
      const profile = this.modelProfiles.find((p) => p.id === this.selectedProfileId);
      return !profile || this.profileName !== profile.name || Boolean(this.settings.api_key)
        || ["provider", "base_url", "model"].some((field) => this.settings[field] !== profile[field]);
    },
    kbSearchActive() {
      return this.kbSearchItems !== null;
    },
    kbTabCategories() {
      if (!this.kbSelected || !Array.isArray(this.kbSelected.categories)) return [];
      return this.kbSelected.categories.filter(
        (cat) => (this.kbTab === "cli") === (cat.id === "cli")
      );
    },
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
      if (nextPage === "kb" && this.kbSoftwares.length === 0) {
        this.loadKbList();
      }
      if (nextPage === "settings" && !this.settingsLoaded) this.loadSettings();
      if (nextPage === "codegen") this.loadCodegenHistory();
    },
  },
  methods: {
    async loadCodegenHistory() {
      try { this.codegenHistory = (await apiFetch("/api/codegen/history")).items; }
      catch (err) { /* 统一错误反馈 */ }
    },
    async generateScript(answering = false) {
      if (this.codegenBusy || !this.codegenForm.requirement.trim()) return;
      if (answering) {
        if (this.clarificationAnswers.some((a) => !a.trim())) {
          showToast("请回答全部追问", "err"); return;
        }
        this.codegenForm.requirement += "\n补充回答：\n" + this.codegenResult.questions.map(
          (q, i) => q + "：" + this.clarificationAnswers[i]).join("\n");
      }
      this.codegenBusy = true;
      this.codegenResult = null;
      try {
        this.codegenResult = await apiFetch("/api/codegen/generate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.codegenForm),
        }, 125000);
        if (this.codegenResult.need_clarification) {
          this.clarificationAnswers = this.codegenResult.questions.map(() => "");
        } else {
          await this.loadCodegenHistory();
          showToast("脚本已生成并保存，执行前请审阅");
        }
      } catch (err) { /* apiFetch 统一反馈 */ }
      finally { this.codegenBusy = false; }
    },
    async openCodegenHistory(item) {
      if (this.codegenBusy) return;
      try {
        this.codegenResult = await apiFetch("/api/codegen/history/" + item.id);
        this.codegenForm = { requirement: this.codegenResult.requirement,
          distro: this.codegenResult.params.distro || "", notes: this.codegenResult.params.notes || "" };
      } catch (err) { /* apiFetch 统一反馈 */ }
    },
    async copyScript() {
      try { await navigator.clipboard.writeText(this.codegenResult.script); showToast("已复制脚本"); }
      catch (err) { showToast("复制失败，请手动选择脚本复制", "err"); }
    },
    downloadScript() {
      const url = URL.createObjectURL(new Blob([this.codegenResult.script], {type: "text/plain;charset=utf-8"}));
      const link = document.createElement("a"); link.href = url; link.download = "opsmate-script.sh";
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    async loadSettings() {
      this.settingsBusy = true;
      try {
        const data = await apiFetch("/api/settings/profiles");
        this.modelProfiles = data.items;
        this.activeProfileId = data.active_id;
        this.selectedProfileId = data.active_id;
        this.selectModelProfile();
        this.settingsLoaded = true;
      } catch (err) { /* apiFetch 已展示错误 */ }
      finally { this.settingsBusy = false; }
    },
    selectModelProfile() {
      const profile = this.modelProfiles.find((p) => p.id === this.selectedProfileId);
      if (!profile) return;
      this.profileName = profile.name;
      this.settings = { provider: profile.provider, base_url: profile.base_url, model: profile.model,
        api_key_set: profile.api_key_set, api_key: "" };
      this.settingsTestResult = "";
    },
    newModelProfile() {
      this.selectedProfileId = "";
      this.profileName = "GLM 付费";
      this.settings = { provider: "zhipu", base_url: "https://open.bigmodel.cn/api/paas/v4",
        model: "", api_key: "", api_key_set: false };
      this.settingsTestResult = "";
    },
    async activateModelProfile() {
      this.settingsBusy = true;
      try {
        await apiFetch("/api/settings/profiles/" + this.selectedProfileId + "/activate", {method: "POST"});
        this.activeProfileId = this.selectedProfileId;
        showToast("已启用该配置，尚未发起模型调用");
      } catch (err) { /* 统一反馈 */ }
      finally { this.settingsBusy = false; }
    },
    applyProviderPreset() {
      const presets = {
        zhipu: ["https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"],
        siliconflow: ["https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B"],
        deepseek: ["https://api.deepseek.com/v1", "deepseek-chat"],
        custom: ["", ""],
      };
      [this.settings.base_url, this.settings.model] = presets[this.settings.provider];
      this.settingsTestResult = "";
    },
    async saveSettings() {
      this.settingsBusy = true;
      try {
        const { provider, base_url, model, api_key } = this.settings;
        const creating = !this.selectedProfileId;
        const saved = await apiFetch("/api/settings/profiles" + (creating ? "" : "/" + this.selectedProfileId),
          { method: creating ? "POST" : "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: this.profileName, provider, base_url, model, api_key }) });
        if (creating) this.selectedProfileId = saved.id;
        this.settings.api_key = "";
        const data = await apiFetch("/api/settings/profiles");
        this.modelProfiles = data.items;
        this.activeProfileId = data.active_id;
        this.selectModelProfile();
        this.settingsTestResult = "";
        showToast("配置已保存到本机" + (this.selectedProfileId === this.activeProfileId ? "" : "，请启用后再测试"));
      } catch (err) { /* apiFetch 已展示错误 */ }
      finally { this.settingsBusy = false; }
    },
    async testSettings() {
      this.settingsTesting = true;
      this.settingsTestResult = "";
      try {
        const data = await apiFetch("/api/llm/test", { method: "POST" }, 60000);
        this.settingsTestResult = data.ok
          ? "连接成功：" + data.model + " · " + data.latency_ms + " ms"
          : data.error;
        showToast(this.settingsTestResult, data.ok ? "ok" : "err");
      } catch (err) { /* apiFetch 已展示错误 */ }
      finally { this.settingsTesting = false; }
    },
    queueKbSearch() {
      clearTimeout(this.kbSearchTimer);
      this.kbSearchTimer = setTimeout(() => this.runKbSearch(), 300);
    },
    async runKbSearch() {
      const query = this.kbQuery.trim();
      if (!query) {
        this.kbSearchItems = null;
        this.kbSearchLoading = false;
        return;
      }
      this.kbSearchLoading = true;
      try {
        const data = await apiFetch("/api/kb/search?q=" + encodeURIComponent(query));
        this.kbSearchItems = data.items;
      } catch (err) {
        this.kbSearchItems = [];
      } finally {
        this.kbSearchLoading = false;
      }
    },
    softwareLabel(software) {
      const hit = this.kbSoftwares.find((item) => item.software === software);
      return hit ? hit.label : software;
    },
    isDanger(level) {
      return level === "medium" || level === "high";
    },
    dangerText(level) {
      return level === "high" ? "高风险" : level === "medium" ? "中风险" : "";
    },
    async loadKbList() {
      this.kbLoading = true;
      try {
        const data = await apiFetch("/api/kb");
        this.kbSoftwares = data.items;
      } finally {
        this.kbLoading = false;
      }
    },
    async openKbSoftware(software) {
      this.kbDetailLoading = true;
      try {
        const data = await apiFetch("/api/kb/" + encodeURIComponent(software));
        this.kbSelected = data;
        this.kbTab = "cli";
        this.kbExpanded = {};
      } finally {
        this.kbDetailLoading = false;
      }
    },
    async jumpKbResult(item) {
      this.kbQuery = "";
      this.kbSearchItems = null;
      this.kbDetailLoading = true;
      try {
        const data = await apiFetch("/api/kb/" + encodeURIComponent(item.software));
        this.kbSelected = data;
        this.kbTab = item.category === "cli" ? "cli" : "conf";
        this.kbExpanded = {};
      } finally {
        this.kbDetailLoading = false;
      }
    },
    backToKb() {
      this.kbSelected = null;
      this.kbExpanded = {};
    },
    toggleKbExpand(name) {
      this.kbExpanded = Object.assign({}, this.kbExpanded, {
        [name]: !this.kbExpanded[name],
      });
    },
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
    if (this.page === "codegen") this.loadCodegenHistory();
    if (this.page === "settings") this.loadSettings();
    window.addEventListener("hashchange", () => {
      this.page = parseRoute();
    });
    if (this.page === "commands") this.loadCommands();
    if (this.page === "kb") this.loadKbList();
  },
  beforeUnmount() {
    clearTimeout(this.commandSearchTimer);
    clearTimeout(this.kbSearchTimer);
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
    '    <section v-else-if="page === \'kb\'" class="kb-page">',
    '      <header class="page-header">',
    "        <div>",
    "          <h1>配置速查</h1>",
    '          <p v-if="!kbSelected">nginx / zabbix 启停命令与配置参数分 Tab 查询</p>',
    '          <p v-else>{{ kbSelected.label }} · {{ kbSelected.version_ref }}</p>',
    "        </div>",
    '        <span class="result-count">AI 整理，使用前请核对官方文档</span>',
    "      </header>",
    '      <label class="command-search">',
    "        <span>搜索</span>",
    '        <input v-model="kbQuery" @input="queueKbSearch" type="search"',
    '               placeholder="跨软件搜索命令或配置参数，例如：worker" autocomplete="off">',
    "      </label>",
    '      <div v-if="kbSearchActive" class="kb-panel">',
    '        <p class="result-count">{{ kbSearchLoading ? "检索中…" : "共 " + kbSearchItems.length + " 条匹配" }}</p>',
    '        <div v-for="item in kbSearchItems" :key="item.software + item.name" class="kb-entry kb-clickable" @click="jumpKbResult(item)">',
    '          <div class="kb-entry-head">',
    "            <strong>{{ item.name }}</strong>",
    '            <span class="kb-soft-tag">{{ softwareLabel(item.software) }} · {{ item.category === "cli" ? "命令" : "配置" }}</span>',
    '            <span v-if="isDanger(item.danger)" class="kb-danger">⚠ {{ dangerText(item.danger) }}</span>',
    "          </div>",
    '          <p class="kb-entry-desc">{{ item.desc }}</p>',
    "        </div>",
    '        <p v-if="!kbSearchLoading && kbSearchItems.length === 0" class="empty-state">未找到匹配条目</p>',
    "      </div>",
    '      <div v-else-if="!kbSelected" class="kb-cards">',
    '        <button v-for="s in kbSoftwares" :key="s.software" type="button" class="kb-card" @click="openKbSoftware(s.software)">',
    "          <h2>{{ s.label }}</h2>",
    "          <p>{{ s.cli_count }} 条启停命令 · {{ s.conf_count }} 条配置参数</p>",
    "        </button>",
    '        <p v-if="kbDetailLoading" class="empty-state">加载中…</p>',
    '        <p v-else-if="!kbLoading && kbSoftwares.length === 0" class="empty-state">知识库为空</p>',
    "      </div>",
    '      <div v-else class="kb-panel">',
    '        <div class="kb-toolbar">',
    '          <button type="button" class="copy-button" @click="backToKb">← 返回软件列表</button>',
    '          <div class="kb-tabs">',
    '            <button type="button" :class="{ active: kbTab === \'cli\' }" @click="kbTab = \'cli\'">启停与运行命令</button>',
    '            <button type="button" :class="{ active: kbTab === \'conf\' }" @click="kbTab = \'conf\'">配置参数</button>',
    "          </div>",
    "        </div>",
    '        <p v-if="kbDetailLoading" class="empty-state">加载中…</p>',
    '        <div v-for="cat in kbTabCategories" :key="cat.label" class="kb-group">',
    '          <h3>{{ cat.label }} <span class="result-count">（{{ (cat.entries || []).length }} 条）</span></h3>',
    '          <div v-for="e in cat.entries" :key="e.name" class="kb-entry">',
    '            <div class="kb-entry-head kb-clickable" @click="toggleKbExpand(e.name)">',
    "              <strong>{{ e.name }}</strong>",
    '              <span v-if="isDanger(e.danger)" class="kb-danger">⚠ {{ dangerText(e.danger) }}</span>',
    '              <code class="kb-syntax">{{ e.syntax }}</code>',
    "            </div>",
    '            <p class="kb-entry-desc">{{ e.desc }}</p>',
    '            <div v-if="kbExpanded[e.name]" class="kb-entry-detail">',
    '              <p v-if="e.default !== undefined && e.default !== null"><span class="kb-field">默认值</span><code>{{ e.default }}</code></p>',
    '              <p v-if="e.section"><span class="kb-field">层级</span><code>{{ e.section }}</code></p>',
    '              <p><span class="kb-field">示例</span><code class="kb-example">{{ e.example }}</code></p>',
    '              <p><span class="kb-field">说明</span>{{ e.notes }}</p>',
    '              <p v-if="e.tags && e.tags.length"><span class="kb-field">标签</span>{{ e.tags.join(" / ") }}</p>',
    "            </div>",
    "          </div>",
    "        </div>",
    "      </div>",
    "    </section>",
    '    <section v-else-if="page === \'codegen\'" class="codegen-page">',
    '      <h1>脚本工坊</h1><p class="placeholder dim">检索本地知识生成脚本；执行前请审阅并在测试环境验证。</p>',
    '      <form class="settings-form" @submit.prevent="generateScript(false)">',
    '        <label>脚本需求<textarea v-model="codegenForm.requirement" required :disabled="codegenBusy" rows="3" placeholder="例如：每天凌晨 2 点打包 /var/log/nginx 目录为 tgz，保留最近 7 天"></textarea></label>',
    '        <label>发行版<select v-model="codegenForm.distro" :disabled="codegenBusy"><option value="">不指定</option><option>CentOS</option><option>Ubuntu</option><option>Debian</option><option>其他</option></select></label>',
    '        <label>补充说明<textarea v-model="codegenForm.notes" :disabled="codegenBusy" rows="2"></textarea></label>',
    '        <button class="copy-button" :disabled="codegenBusy" type="submit">{{ codegenBusy ? "生成中…" : "生成脚本" }}</button>',
    '      </form>',
    '      <section v-if="codegenResult && codegenResult.need_clarification" class="clarification">',
    '        <h2>需要补充信息</h2><form class="settings-form" @submit.prevent="generateScript(true)">',
    '          <label v-for="(q,i) in codegenResult.questions" :key="i">{{ q }}<input required v-model="clarificationAnswers[i]" :disabled="codegenBusy"></label>',
    '          <button class="copy-button" type="submit" :disabled="codegenBusy">补充并重新生成</button>',
    '        </form>',
    '      </section>',
    '      <section v-else-if="codegenResult">',
    '        <h2>生成过程</h2><p v-if="!codegenResult.steps || !codegenResult.steps.length" class="placeholder dim">直接生成</p>',
    '        <details v-for="(step,i) in codegenResult.steps" :key="i" class="trace-card"><summary>{{ i + 1 }} · {{ step.tool }}</summary><pre>{{ JSON.stringify(step.args) }}</pre><p>{{ step.result_summary }}</p></details>',
    '        <div class="codegen-output"><section><div class="settings-actions"><button class="copy-button" @click="copyScript">复制脚本</button><button class="copy-button" @click="downloadScript">下载 .sh</button></div><pre class="script-source">{{ codegenResult.script }}</pre></section>',
    '          <section><h2>逐段解读</h2><article v-for="(part,i) in codegenResult.explanation" :key="i" class="trace-card"><h3><span class="line-badge">{{ part.lines }}</span> {{ part.title }}</h3><p>{{ part.detail }}</p></article>',
    '            <div class="script-warnings"><p v-for="(warning,i) in codegenResult.warnings" :key="i">⚠ {{ warning }}</p></div><p class="script-usage">{{ codegenResult.usage }}</p>',
    '          </section></div>',
    '      </section>',
    '      <h2>生成历史</h2><p v-if="!codegenHistory.length" class="placeholder dim">暂无生成记录</p>',
    '      <button v-for="item in codegenHistory" :key="item.id" class="history-item" :disabled="codegenBusy" @click="openCodegenHistory(item)">{{ item.requirement }} · {{ item.model }} · {{ item.created_at }}</button>',
    '    </section>',
    '    <section v-else-if="page === \'settings\'" class="settings-page">',
    '      <h1>模型设置</h1>',
    '      <p class="placeholder dim">配置 OpenAI 兼容模型服务，保存后再测试连通。</p>',
    '      <div class="settings-form"><label>本机配置<select v-model="selectedProfileId" @change="selectModelProfile" :disabled="settingsBusy || settingsTesting">',
    '        <option v-if="!selectedProfileId" value="">新配置（尚未保存）</option>',
    '        <option v-for="p in modelProfiles" :key="p.id" :value="p.id">{{ p.name }}{{ p.id === activeProfileId ? "（已启用）" : "" }}</option>',
    '      </select></label><button class="copy-button" type="button" @click="newModelProfile" :disabled="settingsBusy || settingsTesting">新增独立配置</button></div>',
    '      <form class="settings-form" @submit.prevent="saveSettings">',
    '        <label>配置名称<input v-model="profileName" required maxlength="80" :disabled="settingsBusy || settingsTesting"></label>',
    '        <label>服务预设<select v-model="settings.provider" @change="applyProviderPreset" :disabled="settingsBusy || settingsTesting">',
    '          <option value="zhipu">智谱 BigModel（默认）</option><option value="siliconflow">硅基流动</option>',
    '          <option value="deepseek">DeepSeek</option><option value="custom">自定义（OpenAI 兼容）</option>',
    '        </select></label>',
    '        <label>base_url<input v-model="settings.base_url" required type="url" :disabled="settingsBusy || settingsTesting"></label>',
    '        <label>模型名称<input v-model="settings.model" required placeholder="填写你账号可调用的完整模型编码" :disabled="settingsBusy || settingsTesting"></label>',
    '        <label>API key<input v-model="settings.api_key" type="password" autocomplete="off"',
    '          :placeholder="settings.api_key_set ? \'••••已保存，留空不修改\' : \'请输入 API key\'" :disabled="settingsBusy || settingsTesting"></label>',
    '        <div class="settings-actions"><button class="copy-button" type="submit" :disabled="settingsBusy || settingsTesting">{{ settingsBusy ? "保存中…" : "保存设置" }}</button>',
    '          <button class="copy-button" type="button" @click="activateModelProfile" :disabled="settingsBusy || settingsTesting || profileHasChanges || selectedProfileId === activeProfileId">启用该配置</button>',
    '          <button class="copy-button" type="button" @click="testSettings" :disabled="settingsBusy || settingsTesting || !settingsLoaded || profileHasChanges || selectedProfileId !== activeProfileId">{{ settingsTesting ? "测试中…" : "测试已启用的配置" }}</button></div>',
    '      </form>',
    '      <p v-if="settingsTestResult" role="status">{{ settingsTestResult }}</p>',
    '      <p class="placeholder dim">配置和密钥仅存本机，不进入 Git、项目分享或安装包。保存与启用不会调用模型；点击测试或生成功能后才会调用，付费模型按平台计费。</p>',
    '      <p class="placeholder dim">推荐预设：智谱 GLM-4-Flash。可在 <a href="https://open.bigmodel.cn" target="_blank" rel="noopener noreferrer">智谱平台</a> 注册并获取 API key；模型供应与计费以平台为准。</p>',
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
