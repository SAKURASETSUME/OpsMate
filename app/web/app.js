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
async function apiFetch(url, options, timeoutMs = 30000, responseType = "json") {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options && options.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener("abort", cancel, {once:true});
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, Object.assign({}, options, { signal: controller.signal }));
    if (!resp.ok) {
      let detail = "";
      try { detail = (await resp.json()).detail || ""; } catch (e) { /* 响应体非 JSON 时忽略 */ }
      throw new Error("HTTP " + resp.status + (detail ? "：" + detail : ""));
    }
    if (typeof responseType === "function") return await responseType(resp);
    return responseType === "blob" ? await resp.blob() : await resp.json();
  } catch (err) {
    if (err.name === "AbortError") {
      if (options && options.signal && options.signal.aborted) showToast("已停止");
      else showToast("请求超时，请检查后端服务", "err");
    } else {
      showToast(String(err.message || err), "err");
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (options && options.signal) options.signal.removeEventListener("abort", cancel);
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

/** 左侧边栏 6 个导航项（契约 §7，顺序固定；运维助手 Phase 8 落地） */
const NAV_ITEMS = [
  { hash: "#/commands",  page: "commands",  label: "指令速查" },
  { hash: "#/kb",        page: "kb",        label: "配置速查" },
  { hash: "#/codegen",   page: "codegen",   label: "脚本工坊" },
  { hash: "#/logs",      page: "logs",      label: "日志中心" },
  { hash: "#/assistant", page: "assistant", label: "运维助手" },
  { hash: "#/settings",  page: "settings",  label: "设置" },
];

/** 各模块施工占位文案 */
const PLACEHOLDER = {
  commands: "指令速查：600+ 中文 Linux 命令离线检索",
  kb: "配置速查：六软件启停命令与配置参数分 Tab 查询",
  codegen: "脚本工坊：自然语言生成带中文注释的 bash 脚本",
  logs: "日志中心：上传 / 粘贴日志，过滤、着色、统计、导出与 AI 分析",
  assistant: "运维助手：基于本地知识库的问答智能体",
  settings: "设置：配置大模型接入",
};

/** 解析当前 hash → 页面名（#/logs/:id 归入 logs 页） */
function parseRoute() {
  const hash = location.hash || "#/commands";
  const name = hash.replace(/^#\//, "").split("/")[0] || "commands";
  return NAV_ITEMS.some((item) => item.page === name) ? name : "commands";
}

/** 分析报告禁止活动 HTML/远程图片，日志或模型正文仅作为显示数据。 */
function reportMarkdown(text) {
  const escape = (value) => String(value || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  const renderer = new marked.Renderer();
  renderer.html = (html) => escape(html);
  renderer.image = (href,title,alt) => escape(alt || "图片");
  renderer.link = (href,title,label) => label + " (" + escape(href) + ")";
  return marked.parse(text.replace(/<!--rehype:[^>]*-->/gi,""), {renderer});
}

/** 纯本地、可复用正则预览，Worker 超时后终止，不阻塞 UI。 */
const RegexPreview = {
  props: { initialPattern: { type: String, default: "Exception|Error" }, initialText: { type: String, default: "" } },
  data() { return { pattern: this.initialPattern, text: this.initialText, flags: "gi", matches: [], error: "", busy: false, worker: null, timer: null }; },
  computed: {
    previewText() { return this.text.slice(0, 20000); },
    segments() {
      const pieces = []; let cursor = 0;
      for (const match of this.matches) {
        pieces.push({ text: this.previewText.slice(cursor, match.index), hit: false });
        pieces.push({ text: match.text || "（零宽匹配）", hit: true });
        cursor = match.index + match.text.length;
      }
      pieces.push({ text: this.previewText.slice(cursor), hit: false });
      return pieces;
    },
  },
  watch: { pattern() { this.preview(); }, text() { this.preview(); }, flags() { this.preview(); } },
  mounted() { this.preview(); },
  beforeUnmount() { clearTimeout(this.timer); if (this.worker) this.worker.terminate(); },
  methods: {
    preview() {
      clearTimeout(this.timer); if (this.worker) this.worker.terminate();
      this.error = ""; this.matches = []; this.busy = false;
      if (!this.pattern) return;
      const code = `onmessage = ({data}) => { try {
        const re = new RegExp(data.pattern, data.flags.includes('g') ? data.flags : data.flags + 'g');
        const matches = []; let match;
        while ((match = re.exec(data.text)) !== null && matches.length < 1000) {
          matches.push({index:match.index,text:match[0],captures:Array.from(match).slice(1),groups:match.groups || {}});
          if (!match[0]) re.lastIndex += data.flags.includes('u') && data.text.codePointAt(re.lastIndex) > 65535 ? 2 : 1;
        }
        postMessage({matches});
      } catch(error) { postMessage({error: String(error.message)}); } };`;
      const url = URL.createObjectURL(new Blob([code], {type: "text/javascript"}));
      try { this.worker = new Worker(url); } catch (err) { this.error = "无法启动正则预览"; URL.revokeObjectURL(url); return; }
      URL.revokeObjectURL(url);
      const worker = this.worker; this.busy = true;
      worker.onmessage = ({data}) => { if (worker !== this.worker) return; clearTimeout(this.timer); this.matches = data.matches || []; this.error = data.error || ""; this.busy = false; worker.terminate(); };
      worker.onerror = () => { clearTimeout(this.timer); this.error = "正则预览失败"; this.busy = false; worker.terminate(); };
      this.timer = setTimeout(() => { worker.terminate(); this.busy = false; this.error = "匹配耗时过长，请简化正则"; }, 700);
      worker.postMessage({pattern:this.pattern,flags:this.flags,text:this.previewText});
    },
  },
  template: `<section class="regex-preview settings-form">
    <label>测试正则<input v-model="pattern" placeholder="Exception|Error"></label>
    <label>正则标志<input v-model="flags" placeholder="gi"></label>
    <label>示例文本<textarea rows="4" v-model="text"></textarea></label>
    <p class="placeholder dim">纯本地预览：最多 20000 字、1000 个匹配；使用浏览器 RegExp，后端过滤使用 Python 正则，高级语法可能不同。</p>
    <p v-if="error" class="regex-error" role="alert">正则无效或无法完成：{{ error }}</p>
    <p v-else role="status">{{ busy ? "预览中…" : "匹配 " + matches.length + " 处" }}</p>
    <pre class="regex-highlight"><template v-for="(part,i) in segments" :key="i"><mark v-if="part.hit">{{ part.text }}</mark><span v-else>{{ part.text }}</span></template></pre>
    <table v-if="matches.length"><thead><tr><th>位置</th><th>匹配内容</th><th>捕获分组</th><th>命名分组</th></tr></thead><tbody><tr v-for="(m,i) in matches" :key="i"><td>{{ m.index }}</td><td>{{ m.text }}</td><td>{{ m.captures.join(" | ") }}</td><td>{{ JSON.stringify(m.groups) }}</td></tr></tbody></table>
  </section>`,
};

const App = {
  components: { RegexPreview },
  data() {
    return {
      page: parseRoute(),
      navItems: NAV_ITEMS,
      backendHost: location.host,
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
      kbTplExpanded: {},
      kbQuery: "",
      kbSearchItems: null,
      kbSearchLoading: false,
      kbSearchTimer: null,
      kbView: "kb",
      wbConfigs: [], wbLoading: false, wbSelectedId: null,
      wbForm: { name: "", format: "yaml", content: "" },
      wbValidation: null, wbBusy: false, wbShowRegex: false, wbShared: false, wbDeleteId: false,
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
      codegenLiveSteps: [], codegenPhase: "", codegenAbort: null,
      logEntries: [], logId: null, currentLog: null, logRows: [], logTotal: 0,
      logsLoading: false, logImporting: false, logTitle: "", logContent: "",
      logLevels: [], logKeyword: "", logUseRegex: false, logPattern: "", logOrder: "asc",
      logFilterTimer: null, logRequestId: 0, logRouteRequestId: 0, showRegexPreview: false,
      pendingDeleteLogId: null,
      analysisOpen: false, analysisBusy: false, analysisContent: "", analysisSteps: [], analysisError: "",
      analysisFocus: "", analysisAbort: null, logReports: [], selectedReportId: "", analysisSaved: false,
      asstSessions: [], asstMessages: [], asstSessionId: null, asstInput: "",
      asstBusy: false, asstAbort: null, asstError: "", pendingDeleteAsstId: null, asstKeySeq: 0,
      paneWidths: { commands: 320, wb: 300, asst: 260, codegen: 0.5 },
    };
  },
  computed: {
    codegenPhaseText() {
      if (this.codegenPhase === "direct") return "直接生成模式：未走工具检索，模型正在写脚本…";
      if (this.codegenPhase === "final") return "资料检索完成，正在生成最终脚本…";
      if (this.codegenPhase === "retry") return "输出未通过校验，正在按提示重试…";
      return "智能体检索本地知识与脚本历史…";
    },
    analysisHtml() { return reportMarkdown(this.analysisContent); },
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
    wbForm: {
      // 内容或格式一旦改动，上一次的校验结果即过期
      handler() { this.wbValidation = null; },
      deep: true,
    },
    page(nextPage) {
      if (nextPage === "commands" && this.commandItems.length === 0) {
        this.loadCommands();
      }
      if (nextPage === "kb" && this.kbSoftwares.length === 0) {
        this.loadKbList();
      }
      if (nextPage === "settings" && !this.settingsLoaded) this.loadSettings();
      if (nextPage === "codegen") this.loadCodegenHistory();
      if (nextPage === "assistant" && !this.asstSessions.length) this.loadAsstSessions();
    },
  },
  methods: {
    async refreshLogsRoute() {
      if (this.analysisAbort) this.analysisAbort.abort();
      this.analysisOpen = false; this.logReports = []; this.selectedReportId = "";
      clearTimeout(this.logFilterTimer); ++this.logRequestId;
      const ticket = ++this.logRouteRequestId;
      const match = location.hash.match(/^#\/logs\/(\d+)$/);
      this.logId = match ? Number(match[1]) : null;
      this.currentLog = null; this.logRows = []; this.logTotal = 0; this.showRegexPreview = false;
      this.logLevels = []; this.logKeyword = ""; this.logUseRegex = false; this.logPattern = ""; this.logOrder = "asc";
      if (!this.logId) { await this.loadLogList(); return; }
      this.logsLoading = true;
      try {
        const data = await apiFetch("/api/logs/" + this.logId);
        if (ticket !== this.logRouteRequestId) return;
        this.currentLog = data;
        await this.loadLogReports();
        await this.loadLogLines(false);
      } catch (err) { /* 统一提示 */ }
      finally { if (ticket === this.logRouteRequestId) this.logsLoading = false; }
    },
    async loadLogList() {
      this.logsLoading = true;
      try { this.logEntries = (await apiFetch("/api/logs")).items; }
      catch (err) { /* 统一提示 */ }
      finally { this.logsLoading = false; }
    },
    async uploadLogFile(file) {
      if (!file || this.logImporting) return;
      if (file.size > 50 * 1024 * 1024) { showToast("日志超过 50MB，请先 split/grep 裁剪", "err"); return; }
      this.logImporting = true;
      try {
        const form = new FormData(); form.append("file", file);
        const result = await apiFetch("/api/logs", {method:"POST",body:form}, 60000);
        showToast("日志导入成功"); location.hash = "#/logs/" + result.id;
      } catch (err) { /* 统一提示 */ }
      finally { this.logImporting = false; }
    },
    async chooseLogFile(event) { await this.uploadLogFile(event.target.files[0]); event.target.value = ""; },
    async dropLogFile(event) { await this.uploadLogFile(event.dataTransfer.files[0]); },
    async pasteLog() {
      if (this.logImporting) return;
      this.logImporting = true;
      try {
        const result = await apiFetch("/api/logs", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:this.logTitle,content:this.logContent})}, 60000);
        this.logTitle = ""; this.logContent = ""; showToast("日志导入成功"); location.hash = "#/logs/" + result.id;
      } catch (err) { /* 统一提示 */ }
      finally { this.logImporting = false; }
    },
    async deleteLog(item) {
      try {
        await apiFetch("/api/logs/" + item.id, {method:"DELETE"}); this.pendingDeleteLogId = null;
        showToast("日志及原始副本已删除"); await this.loadLogList();
      } catch (err) { /* 统一提示 */ }
    },
    logFilterParams() {
      const params = new URLSearchParams();
      if (this.logLevels.length) params.set("level", this.logLevels.join(","));
      if (this.logKeyword) params.set("q", this.logKeyword);
      if (this.logUseRegex && this.logPattern) params.set("regex", this.logPattern);
      return params;
    },
    queueLogFilter() { clearTimeout(this.logFilterTimer); this.logFilterTimer = setTimeout(() => this.loadLogLines(false), 300); },
    async loadLogLines(append = false) {
      if (!this.logId || (append && this.logsLoading)) return;
      const ticket = ++this.logRequestId; const id = this.logId;
      const params = this.logFilterParams(); params.set("offset", append ? this.logRows.length : 0);
      params.set("limit", 500); params.set("order", this.logOrder);
      this.logsLoading = true;
      if (!append) { this.logRows = []; this.logTotal = 0; }
      try {
        const data = await apiFetch("/api/logs/" + id + "/lines?" + params);
        if (ticket !== this.logRequestId || id !== this.logId) return;
        this.logRows = append ? this.logRows.concat(data.lines) : data.lines; this.logTotal = data.total;
      } catch (err) { /* 统一提示 */ }
      finally { if (ticket === this.logRequestId) this.logsLoading = false; }
    },
    async exportLog() {
      try {
        const blob = await apiFetch("/api/logs/" + this.logId + "/export?" + this.logFilterParams(), undefined, 60000, "blob");
        const url = URL.createObjectURL(blob); const link = document.createElement("a");
        link.href = url; link.download = "opsmate-log-" + this.logId + ".txt"; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000); showToast("已导出过滤后的全部日志（含原行号）");
      } catch (err) { /* 统一提示 */ }
    },
    async loadLogReports() {
      if (!this.logId) return;
      const id = this.logId;
      try { const data = await apiFetch("/api/logs/" + id + "/reports"); if (id === this.logId) this.logReports = data.items; }
      catch (err) { /* 统一提示 */ }
    },
    openAnalysis() {
      if (this.analysisBusy) { this.analysisOpen = true; return; }
      this.analysisOpen = true; this.analysisContent = ""; this.analysisSteps = []; this.analysisError = ""; this.analysisSaved = false; this.selectedReportId = "";
    },
    closeAnalysis() { if (this.analysisAbort) this.analysisAbort.abort(); this.analysisOpen = false; },
    async startAnalysis() {
      if (this.analysisBusy || !this.logId) return;
      const id = this.logId; const controller = new AbortController(); this.analysisAbort = controller;
      this.analysisBusy = true; this.analysisSaved = false; this.analysisError = ""; this.analysisSteps = []; this.analysisContent = "";
      try {
        await apiFetch("/api/logs/" + id + "/llm-analyze", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({focus:this.analysisFocus}),signal:controller.signal}, 305000, async (response) => {
          const reader = response.body.getReader(); const decoder = new TextDecoder("utf-8"); let buffer = ""; let completed = false;
          const accept = (line) => {
            if (!line.startsWith("data:")) return;
            const event = JSON.parse(line.slice(5).trim());
            if (event.error) throw new Error(event.error);
            if (event.tool) this.analysisSteps.push({tool:event.tool,args:event.args,result:event.result});
            if (event.delta) this.analysisContent += event.delta;
            if (event.done) { completed = true; this.analysisSaved = true; this.selectedReportId = String(event.report_id); }
          };
          try {
            while (true) {
              const {value,done} = await reader.read();
              buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
              const lines = buffer.split(/\r?\n/); buffer = lines.pop(); lines.forEach(accept);
              if (done) { if (buffer.trim()) accept(buffer); break; }
            }
            if (!completed) throw new Error("分析连接中断，报告未保存");
          } finally { if (!completed) { try { await reader.cancel(); } catch (err) { /* 已断开的连接 */ } } reader.releaseLock(); }
        });
        if (id === this.logId) await this.loadLogReports();
        showToast("报告已保存，可从历史报告重新打开");
      } catch (err) {
        if (err.name !== "AbortError") this.analysisError = String(err.message || err);
      } finally { this.analysisBusy = false; this.analysisAbort = null; }
    },
    async openReport() {
      if (!this.selectedReportId || this.analysisBusy) return;
      try {
        const data = await apiFetch("/api/logs/" + this.logId + "/reports/" + this.selectedReportId);
        this.analysisContent = data.content; this.analysisSteps = []; this.analysisError = ""; this.analysisSaved = true; this.analysisOpen = true;
      } catch (err) { /* 统一提示 */ }
    },
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
      this.codegenLiveSteps = [];
      this.codegenPhase = "";
      const controller = new AbortController(); this.codegenAbort = controller;
      try {
        await apiFetch("/api/codegen/generate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.codegenForm), signal: controller.signal,
        }, 125000, async (response) => {
          const reader = response.body.getReader(); const decoder = new TextDecoder("utf-8"); let buffer = ""; let completed = false;
          const accept = (line) => {
            if (!line.startsWith("data:")) return;
            const event = JSON.parse(line.slice(5).trim());
            if (event.error) throw new Error(event.error);
            if (event.tool) this.codegenLiveSteps.push({ tool: event.tool, args: event.args, result_summary: event.result });
            if (event.phase) this.codegenPhase = event.phase;
            if (event.result && !event.tool) this.codegenResult = event.result;
            if (event.done) completed = true;
          };
          try {
            while (true) {
              const {value, done} = await reader.read();
              buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
              const lines = buffer.split(/\r?\n/); buffer = lines.pop(); lines.forEach(accept);
              if (done) { if (buffer.trim()) accept(buffer); break; }
            }
            if (!completed) throw new Error("生成连接中断，本轮未保存");
          } finally { if (!completed) { try { await reader.cancel(); } catch (err) { /* 已断开的连接 */ } reader.releaseLock(); } }
        });
        if (this.codegenResult && this.codegenResult.need_clarification) {
          this.clarificationAnswers = this.codegenResult.questions.map(() => "");
        } else {
          await this.loadCodegenHistory();
          showToast("脚本已生成并保存，执行前请审阅");
        }
      } catch (err) {
        if (err.name !== "AbortError") showToast(String(err.message || err), "err");
      } finally { this.codegenBusy = false; this.codegenAbort = null; }
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
        this.kbTplExpanded = {};
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
        this.kbTplExpanded = {};
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
    toggleKbTpl(name) {
      this.kbTplExpanded = Object.assign({}, this.kbTplExpanded, {
        [name]: !this.kbTplExpanded[name],
      });
    },
    async copyText(text, message) {
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(text);
        } else {
          const textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          const copied = document.execCommand("copy");
          textarea.remove();
          if (!copied) throw new Error("浏览器未允许写入剪贴板");
        }
        showToast(message);
      } catch (err) {
        showToast("复制失败：" + String(err.message || err), "err");
      }
    },
    copyKbTemplate(tpl) { this.copyText(tpl.content, "模板已复制，替换占位符后即可使用"); },
    switchKbView(view) {
      this.kbView = view;
      if (view === "mine" && !this.wbConfigs.length) this.loadWbConfigs();
    },
    async loadWbConfigs() {
      this.wbLoading = true;
      try { this.wbConfigs = (await apiFetch("/api/kb/workbench/configs")).items; }
      catch (err) { /* 统一提示 */ }
      finally { this.wbLoading = false; }
    },
    newWbConfig() {
      this.wbSelectedId = null;
      this.wbForm = { name: "", format: "yaml", content: "" };
      this.wbValidation = null; this.wbShared = false; this.wbShowRegex = false; this.wbDeleteId = false;
    },
    async openWbConfig(item) {
      this.wbBusy = true;
      try {
        const data = await apiFetch("/api/kb/workbench/configs/" + item.id);
        this.wbSelectedId = data.id;
        this.wbForm = { name: data.name, format: data.format, content: data.content };
        this.wbShared = data.shared === 1;
        this.wbValidation = null; this.wbShowRegex = false; this.wbDeleteId = false;
      } catch (err) { /* 统一提示 */ }
      finally { this.wbBusy = false; }
    },
    async uploadWbFile(event) {
      const file = event.target.files[0];
      event.target.value = "";
      if (!file) return;
      if (file.size > 2 * 1024 * 1024) { showToast("配置内容超过 2MB 上限，请先拆分", "err"); return; }
      try {
        this.wbForm.content = await file.text();
        showToast("已按 UTF-8 读入：" + file.name);
      } catch (err) { showToast("读取文件失败", "err"); }
    },
    jumpWbLine(line) {
      const editor = document.getElementById("wb-editor-content");
      if (!editor || !line || line < 1) return;
      const lines = this.wbForm.content.split(/\r?\n/);
      if (line > lines.length) return;
      let start = 0;
      for (let index = 0; index < line - 1; index++) start += lines[index].length + 1;
      editor.focus();
      editor.setSelectionRange(start, start + lines[line - 1].length);
      const lineHeight = parseFloat(getComputedStyle(editor).lineHeight) || 20;
      editor.scrollTop = Math.max(0, (line - 3) * lineHeight);
    },
    async validateWbConfig() {
      this.wbBusy = true;
      try {
        this.wbValidation = await apiFetch("/api/kb/workbench/validate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ format: this.wbForm.format, content: this.wbForm.content }),
        });
        showToast(this.wbValidation.ok ? "校验通过" : "发现 " + this.wbValidation.errors.length + " 处错误",
          this.wbValidation.ok ? "ok" : "err");
      } catch (err) { /* 统一提示 */ }
      finally { this.wbBusy = false; }
    },
    async saveWbConfig() {
      if (this.wbBusy || !this.wbForm.name.trim()) return;
      this.wbBusy = true;
      try {
        const creating = this.wbSelectedId === null;
        const saved = await apiFetch("/api/kb/workbench/configs" + (creating ? "" : "/" + this.wbSelectedId), {
          method: creating ? "POST" : "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.wbForm),
        });
        if (creating) this.wbSelectedId = saved.id;
        this.wbDeleteId = false;
        showToast("配置已保存（仅本机）");
        await this.loadWbConfigs();
      } catch (err) { /* 统一提示 */ }
      finally { this.wbBusy = false; }
    },
    async toggleWbShare() {
      if (this.wbSelectedId === null || this.wbBusy) return;
      this.wbBusy = true;
      try {
        const data = await apiFetch("/api/kb/workbench/configs/" + this.wbSelectedId + "/share", {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ shared: !this.wbShared }),
        });
        this.wbShared = data.shared === 1;
        showToast(this.wbShared ? "已共享：智能体现在可读取该配置" : "已关闭共享，立即生效");
        await this.loadWbConfigs();
      } catch (err) { /* 统一提示 */ }
      finally { this.wbBusy = false; }
    },
    async deleteWbConfig() {
      if (this.wbSelectedId === null || this.wbBusy) return;
      this.wbBusy = true;
      try {
        await apiFetch("/api/kb/workbench/configs/" + this.wbSelectedId, { method: "DELETE" });
        showToast("配置已删除");
        this.newWbConfig();
        await this.loadWbConfigs();
      } catch (err) { /* 统一提示 */ }
      finally { this.wbBusy = false; }
    },
    /* ============ 可拖拽分割条 ============ */
    gridPaneStyle(key) {
      if (key === "codegen") {
        const left = Math.min(0.75, Math.max(0.25, this.paneWidths.codegen));
        return { gridTemplateColumns: `minmax(0, ${left}fr) 6px minmax(0, ${1 - left}fr)` };
      }
      return { gridTemplateColumns: `${this.paneWidths[key]}px 6px minmax(0, 1fr)` };
    },
    startPaneDrag(event, key) {
      if (event.button !== 0) return;
      event.preventDefault();
      const limits = { commands: [180, 640], wb: [200, 720], asst: [200, 520] }[key];
      const startX = event.clientX;
      const startWidth = this.paneWidths[key];
      const totalPx = Math.max(event.currentTarget.parentElement.clientWidth - 6, 1);
      const startRatio = this.paneWidths.codegen;
      const splitter = event.currentTarget;
      splitter.classList.add("active");
      document.body.classList.add("pane-dragging");
      const onMove = (moveEvent) => {
        const delta = moveEvent.clientX - startX;
        if (key === "codegen") {
          this.paneWidths.codegen = Math.round(Math.min(0.75, Math.max(0.25, startRatio + delta / totalPx)) * 1000) / 1000;
        } else {
          this.paneWidths[key] = Math.round(Math.min(limits[1], Math.max(limits[0], startWidth + delta)));
        }
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        splitter.classList.remove("active");
        document.body.classList.remove("pane-dragging");
        try { localStorage.setItem("opsmate-pane-widths", JSON.stringify(this.paneWidths)); } catch (err) { /* 忽略持久化失败 */ }
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    /* ============ 运维助手（Phase 8） ============ */
    async loadAsstSessions() {
      try { this.asstSessions = (await apiFetch("/api/assistant/sessions")).items; }
      catch (err) { /* 统一提示 */ }
    },
    newAsstSession() {
      if (this.asstBusy) return;
      this.asstSessionId = null; this.asstMessages = []; this.asstError = ""; this.pendingDeleteAsstId = null;
    },
    parseAsstRow(row) {
      if (row.role !== "tool") {
        return { key: row.role[0] + row.id, role: row.role, content: row.content, tools: [] };
      }
      try {
        const trace = JSON.parse(row.content);
        return { key: "t" + row.id, role: "tool", tool: trace.tool || "", args: trace.args || {}, result: trace.result || "" };
      } catch (err) {
        return { key: "t" + row.id, role: "tool", tool: "", args: {}, result: row.content };
      }
    },
    async openAsstSession(item) {
      if (this.asstBusy) return;
      try {
        const data = await apiFetch("/api/assistant/sessions/" + item.id);
        this.asstSessionId = item.id;
        this.asstMessages = data.messages.map((row) => this.parseAsstRow(row));
        this.asstError = ""; this.pendingDeleteAsstId = null;
      } catch (err) { /* 统一提示 */ }
    },
    async deleteAsstSession(item) {
      if (this.asstBusy) return;
      try {
        await apiFetch("/api/assistant/sessions/" + item.id, { method: "DELETE" });
        this.pendingDeleteAsstId = null;
        showToast("会话已删除");
        if (this.asstSessionId === item.id) this.newAsstSession();
        await this.loadAsstSessions();
      } catch (err) { /* 统一提示 */ }
    },
    askKeydown(event) {
      if (event.isComposing) return; // 中文输入法选词回车不发送
      this.sendAsstMessage();
    },
    async sendAsstMessage() {
      if (this.asstBusy || !this.asstInput.trim()) return;
      const message = this.asstInput.trim();
      this.asstInput = ""; this.asstError = "";
      this.asstMessages.push({ key: "u" + (++this.asstKeySeq), role: "user", content: message, tools: [] });
      const live = { key: "a" + (++this.asstKeySeq), role: "assistant", content: "", tools: [] };
      this.asstMessages.push(live);
      const controller = new AbortController(); this.asstAbort = controller;
      this.asstBusy = true;
      try {
        await apiFetch("/api/assistant/chat", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, session_id: this.asstSessionId }),
          signal: controller.signal,
        }, 305000, async (response) => {
          const reader = response.body.getReader(); const decoder = new TextDecoder("utf-8"); let buffer = ""; let completed = false;
          const accept = (line) => {
            if (!line.startsWith("data:")) return;
            const event = JSON.parse(line.slice(5).trim());
            if (event.error) throw new Error(event.error);
            if (event.tool) live.tools.push({ tool: event.tool, args: event.args, result: event.result });
            if (event.delta) live.content += event.delta;
            if (event.done) { completed = true; this.asstSessionId = event.session_id; }
          };
          try {
            while (true) {
              const {value, done} = await reader.read();
              buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
              const lines = buffer.split(/\r?\n/); buffer = lines.pop(); lines.forEach(accept);
              if (done) { if (buffer.trim()) accept(buffer); break; }
            }
            if (!completed) throw new Error("回答连接中断，本轮未保存");
          } finally { if (!completed) { try { await reader.cancel(); } catch (err) { /* 已断开的连接 */ } reader.releaseLock(); } }
        });
        await this.loadAsstSessions();
      } catch (err) {
        if (err.name !== "AbortError") this.asstError = String(err.message || err);
        if (!live.content && !live.tools.length) this.asstMessages.pop();
      } finally { this.asstBusy = false; this.asstAbort = null; }
    },
    assistantMarkdown(text) {
      // 来源标记 → 站内链接：【命令：tar】→#/commands/tar；【配置：nginx/name】→#/kb/nginx/name
      const withLinks = String(text || "")
        .replace(/【命令：([^】]+)】/g, (m, name) => "[`" + name.trim() + "`](#/commands/" + encodeURIComponent(name.trim()) + ")")
        .replace(/【配置：([^】/]+)\/([^】]+)】/g, (m, software, entry) =>
          "[`" + software.trim() + "/" + entry.trim() + "`](#/kb/" + encodeURIComponent(software.trim()) + "/" + encodeURIComponent(entry.trim()) + ")");
      const escape = (value) => String(value || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
      const renderer = new marked.Renderer();
      renderer.html = (html) => escape(html);
      renderer.image = (href,title,alt) => escape(alt || "图片");
      renderer.link = (href, title, label) => (href && href.indexOf("#/") === 0)
        ? '<a href="' + escape(href) + '">' + label + "</a>"
        : label + " (" + escape(href) + ")";
      return marked.parse(withLinks.replace(/<!--rehype:[^>]*-->/gi,""), {renderer});
    },
    async handleDeepLink() {
      // #/commands/<name> 与 #/kb/<software>/<entry>：来源引用跳转
      const parts = location.hash.replace(/^#\/?/, "").split("/");
      if (this.page === "commands" && parts[1]) {
        if (!this.commandItems.length) this.loadCommands();
        this.selectCommand(decodeURIComponent(parts[1]));
      } else if (this.page === "kb" && parts[1]) {
        this.kbView = "kb"; this.kbQuery = ""; this.kbSearchItems = null;
        const software = decodeURIComponent(parts[1]);
        const entry = parts[2] ? decodeURIComponent(parts.slice(2).join("/")) : "";
        this.kbDetailLoading = true;
        try {
          const data = await apiFetch("/api/kb/" + encodeURIComponent(software));
          this.kbSelected = data;
          this.kbExpanded = {};
          this.kbTplExpanded = {};
          if (entry) {
            const hit = (data.categories || []).find((cat) =>
              (cat.entries || []).some((e) => e.name === entry));
            this.kbTab = hit && hit.id === "conf" ? "conf" : "cli";
            this.kbExpanded = { [entry]: true };
          } else {
            this.kbTab = "cli";
          }
        } catch (err) { /* 统一提示 */ }
        finally { this.kbDetailLoading = false; }
      }
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
    try {
      const saved = JSON.parse(localStorage.getItem("opsmate-pane-widths") || "{}");
      Object.assign(this.paneWidths, saved);
    } catch (err) { /* 本地存储不可用时用默认宽度 */ }
    if (this.page === "logs") this.refreshLogsRoute();
    if (this.page === "codegen") this.loadCodegenHistory();
    if (this.page === "settings") this.loadSettings();
    if (this.page === "assistant") this.loadAsstSessions();
    window.addEventListener("hashchange", () => {
      if (this.analysisAbort) this.analysisAbort.abort();
      this.page = parseRoute();
      if (this.page === "logs") this.refreshLogsRoute();
      if (this.page === "assistant" && !this.asstSessions.length) this.loadAsstSessions();
      this.handleDeepLink();
    });
    if (this.page === "commands") this.loadCommands();
    if (this.page === "kb") this.loadKbList();
    this.handleDeepLink();
  },
  beforeUnmount() {
    if (this.analysisAbort) this.analysisAbort.abort();
    clearTimeout(this.commandSearchTimer);
    clearTimeout(this.kbSearchTimer);
    clearTimeout(this.logFilterTimer);
  },
  template: [
    '<div class="layout">',
    '  <aside class="sidebar">',
    '    <div class="logo">OpsMate</div>',
    '    <p class="logo-sub">运维提效智能体</p>',
    '    <nav>',
    '      <a v-for="item in navItems" :key="item.hash" :href="item.hash"',
    '         :class="{ active: page === item.page }">{{ item.label }}</a>',
    "    </nav>",
    '    <div class="side-status"><span class="status-dot"></span><span>{{ backendHost }}</span></div>',
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
    '      <div class="command-browser" :style="gridPaneStyle(\'commands\')">',
    '        <aside class="command-list" aria-label="命令搜索结果">',
    '          <button v-for="item in commandItems" :key="item.name" type="button"',
    '                  :class="{ active: selectedCommand && selectedCommand.name === item.name }"',
    '                  @click="selectCommand(item.name)">',
    '            <strong>{{ item.name }}</strong><span>{{ item.title }}</span>',
    '          </button>',
    '          <p v-if="!commandLoading && commandItems.length === 0" class="empty-state">未找到匹配命令</p>',
    '        </aside>',
    '        <div class="pane-splitter" title="拖拽调整宽度" @mousedown="startPaneDrag($event, \'commands\')"></div>',
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
    '          <div class="kb-view-tabs" role="tablist">',
    '            <button type="button" :class="{ active: kbView === \'kb\' }" @click="switchKbView(\'kb\')">知识库</button>',
    '            <button type="button" :class="{ active: kbView === \'mine\' }" @click="switchKbView(\'mine\')">我的配置</button>',
    "          </div>",
    "        </div>",
    '        <span class="result-count">AI 整理，使用前请核对官方文档</span>',
    "      </header>",
    "      <template v-if=\"kbView === 'kb'\">",
    '      <p v-if="!kbSelected" class="placeholder dim">nginx / zabbix / keepalived / kafka / redis / docker 启停命令与配置参数分 Tab 查询</p>',
    '      <p v-else class="placeholder dim">{{ kbSelected.label }} · {{ kbSelected.version_ref }}</p>',
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
    '          <div class="kb-card-stats"><span><b>{{ s.cli_count }}</b>启停命令</span><span><b>{{ s.conf_count }}</b>配置参数</span></div>',
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
    '            <button v-if="kbSelected.templates && kbSelected.templates.length" type="button" :class="{ active: kbTab === \'tpl\' }" @click="kbTab = \'tpl\'">推荐模板</button>',
    "          </div>",
    "        </div>",
    '        <p v-if="kbDetailLoading" class="empty-state">加载中…</p>',
    '        <div v-if="kbTab === \'tpl\'" class="kb-group">',
    '          <h3>推荐配置模板 <span class="result-count">（{{ (kbSelected.templates || []).length }} 份，可复制直接使用）</span></h3>',
    '          <div v-for="tpl in kbSelected.templates" :key="tpl.name" class="kb-entry">',
    '            <div class="kb-entry-head kb-clickable" @click="toggleKbTpl(tpl.name)">',
    "              <strong>{{ tpl.name }}</strong>",
    "            </div>",
    '            <p class="kb-entry-desc">{{ tpl.desc }}</p>',
    '            <div v-if="kbTplExpanded[tpl.name]" class="kb-entry-detail">',
    '              <div class="settings-actions"><button class="copy-button" type="button" @click="copyKbTemplate(tpl)">复制模板</button></div>',
    '              <pre class="kb-tpl-content">{{ tpl.content }}</pre>',
    "            </div>",
    "          </div>",
    "        </div>",
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
    "    </template>",
    '    <div v-else class="wb-layout" :style="gridPaneStyle(\'wb\')">',
    '      <aside class="wb-list" aria-label="我的配置列表">',
    '        <button class="copy-button" type="button" @click="newWbConfig" :disabled="wbBusy">＋ 新建配置</button>',
    '        <p v-if="wbLoading" class="empty-state">加载中…</p>',
    '        <p v-else-if="!wbConfigs.length" class="empty-state">暂无配置：新建或上传一份配置开始校验</p>',
    '        <button v-for="item in wbConfigs" :key="item.id" type="button" class="history-item"',
    '                :class="{ active: wbSelectedId === item.id }" @click="openWbConfig(item)">',
    "          <strong>{{ item.name }}</strong>",
    '          <span class="wb-meta">{{ item.format }} · {{ item.size_bytes }} 字节 · {{ item.updated_at }}<em v-if="item.shared" class="wb-shared-badge">已共享</em></span>',
    "        </button>",
    "      </aside>",
    '      <div class="pane-splitter" title="拖拽调整宽度" @mousedown="startPaneDrag($event, \'wb\')"></div>',
    '      <section class="wb-editor" aria-label="配置编辑器">',
    '        <p class="placeholder dim">配置仅保存在本机数据库；校验为本地静态分析，不联网、不执行。单份内容不超过 2MB。</p>',
    '        <div class="settings-form">',
    '          <label>配置名称<input v-model="wbForm.name" maxlength="80" :disabled="wbBusy" placeholder="例如：生产 nginx 主配置"></label>',
    '          <label>格式<select v-model="wbForm.format" :disabled="wbBusy">',
    '            <option value="yaml">YAML</option><option value="nginx">nginx</option>',
    '            <option value="keepalived">keepalived</option><option value="properties">properties（zabbix / kafka / redis）</option>',
    '            <option value="json">JSON</option><option value="text">纯文本</option></select></label>',
    '          <label>配置内容（UTF-8 文本）<textarea id="wb-editor-content" v-model="wbForm.content" rows="14" spellcheck="false" :disabled="wbBusy" class="code-input" placeholder="粘贴配置内容，或点击下方按钮选择文件"></textarea></label>',
    '          <div class="settings-actions">',
    '            <label class="copy-button wb-upload-btn">选择文件上传<input type="file" :disabled="wbBusy" accept=".yaml,.yml,.conf,.cfg,.properties,.json,.txt" @change="uploadWbFile"></label>',
    '            <button class="copy-button" type="button" @click="validateWbConfig" :disabled="wbBusy">校验</button>',
    '            <button class="copy-button" type="button" @click="wbShowRegex = !wbShowRegex">正则测试</button>',
    '            <button class="copy-button" type="button" @click="saveWbConfig" :disabled="wbBusy || !wbForm.name.trim()">{{ wbBusy ? "处理中…" : "保存" }}</button>',
    '            <button v-if="wbSelectedId !== null" class="copy-button danger-button" type="button" @click="wbDeleteId = true" :disabled="wbBusy">删除</button>',
    "          </div>",
    '          <div v-if="wbDeleteId" class="delete-confirm">',
    "            <p>确认删除该配置？此操作不可撤销。</p>",
    '            <button class="copy-button danger-button" type="button" @click="deleteWbConfig" :disabled="wbBusy">确认删除</button>',
    '            <button class="copy-button" type="button" @click="wbDeleteId = false">取消</button>',
    "          </div>",
    '          <div v-if="wbSelectedId !== null" class="wb-share-row">',
    '            <label class="inline-label"><input type="checkbox" :checked="wbShared" :disabled="wbBusy" @change="toggleWbShare">共享给智能体（可被工具 read_user_config 读取）</label>',
    '            <p class="wb-share-hint">⚠ 开启后该配置内容会被发送给大模型；关闭立即生效。包含密钥、口令等敏感信息的配置请勿开启。</p>',
    "          </div>",
    "        </div>",
    '        <div v-if="wbValidation" class="wb-results">',
    '          <p :class="wbValidation.ok ? \'wb-ok\' : \'regex-error\'" role="status">{{ wbValidation.ok ? "校验通过" : "发现 " + wbValidation.errors.length + " 处错误" }} · {{ wbValidation.stats.lines }} 行 · {{ wbValidation.stats.bytes }} 字节</p>',
    '          <div class="wb-issues">',
    '            <p v-for="(issue,i) in wbValidation.errors" :key="\'e\'+i" class="wb-issue err" title="点击定位到该行" @click="jumpWbLine(issue.line)">',
    '              <span class="wb-line-no">{{ issue.line ? "第 " + issue.line + " 行" : "全局" }}</span>{{ issue.message }}</p>',
    '            <p v-for="(issue,i) in wbValidation.warnings" :key="\'w\'+i" class="wb-issue warn" title="点击定位到该行" @click="jumpWbLine(issue.line)">',
    '              <span class="wb-line-no">{{ issue.line ? "第 " + issue.line + " 行" : "全局" }}</span>{{ issue.message }}</p>',
    "          </div>",
    "        </div>",
    '        <regex-preview v-if="wbShowRegex" initial-pattern="(\\w+)@(\\w+\\.\\w+)" :initial-text="wbForm.content.slice(0, 20000)"></regex-preview>',
    "      </section>",
    "    </div>",
    '    </section>',
    '    <section v-else-if="page === \'logs\'" class="logs-page">',
    '      <template v-if="!logId">',
    '        <h1>日志中心</h1><p class="placeholder dim">本机导入、过滤与导出；单份日志不超过 50MB，使用 UTF-8 编码。</p>',
    '        <form class="settings-form log-import" @submit.prevent="pasteLog">',
    '          <div class="log-drop" @dragover.prevent @drop.prevent="dropLogFile">',
    '            <p class="log-drop-hint">{{ logImporting ? "导入中…" : "拖拽日志文件到此处，或使用下方按钮导入" }}</p>',
    '            <div class="log-upload-actions">',
    '              <label class="copy-button">选择日志文件<input type="file" @change="chooseLogFile" :disabled="logImporting" accept=".log,.txt,.out,.json"></label>',
    '              <button class="copy-button" type="submit" :disabled="logImporting">导入粘贴日志</button>',
    "            </div>",
    "          </div>",
    '          <label>日志标题<input v-model="logTitle" required maxlength="200" :disabled="logImporting" placeholder="粘贴导入时必填"></label>',
    '          <label>粘贴日志<textarea v-model="logContent" rows="5" required :disabled="logImporting"></textarea></label>',
    "        </form>",
    '        <h2>本机日志</h2><p v-if="logsLoading">加载中…</p><p v-else-if="!logEntries.length" class="placeholder dim">暂无日志，请上传文件或粘贴文本。</p>',
    '        <article v-for="item in logEntries" :key="item.id" class="trace-card"><h3>{{ item.title }}</h3><p class="placeholder dim">{{ item.line_count }} 行 · {{ item.size_bytes }} 字节 · {{ item.format_guess }} · {{ item.created_at }}</p><p><span v-for="(count,level) in item.level_stats" :key="level" :class="[\'level-badge\',\'level-\'+(level || \'UNKNOWN\')]">{{ level || "未知" }} {{ count }}</span></p><div class="settings-actions"><a class="copy-button" :href="\'#/logs/\'+item.id">查看 / 分析</a><button class="copy-button danger-button" @click="pendingDeleteLogId=item.id">删除</button></div><div v-if="pendingDeleteLogId===item.id" class="delete-confirm"><p>确认删除此日志、行数据和原始副本？此操作不可撤销。</p><button class="copy-button danger-button" @click="deleteLog(item)">确认删除</button><button class="copy-button" @click="pendingDeleteLogId=null">取消</button></div></article>',
    '      </template>',
    '      <template v-else><a href="#/logs" class="back-link">← 返回日志列表</a><p v-if="!currentLog">{{ logsLoading ? "加载日志中…" : "日志不存在或加载失败" }}</p>',
    '        <template v-if="currentLog"><h1>{{ currentLog.title }}</h1><p class="placeholder dim">{{ currentLog.line_count }} 行 · {{ currentLog.size_bytes }} 字节 · {{ currentLog.format_guess }}</p>',
    '          <p><span v-for="(count,level) in currentLog.level_stats" :key="level" :class="[\'level-badge\',\'level-\'+(level || \'UNKNOWN\')]">{{ level || "未知" }} {{ count }}</span></p>',
    '          <div class="log-toolbar">',
    '            <fieldset><legend>级别过滤（未勾选表示全部）</legend><label v-for="level in [\'ERROR\',\'WARN\',\'INFO\',\'DEBUG\',\'UNKNOWN\']" :key="level"><input type="checkbox" v-model="logLevels" :value="level" @change="loadLogLines(false)">{{ level === "UNKNOWN" ? "未知" : level }}</label></fieldset>',
    '            <div class="log-toolbar-row">',
    '              <label>关键词<input class="log-kw" v-model="logKeyword" @input="queueLogFilter" placeholder="大小写不敏感子串"></label>',
    '              <label class="inline-label"><input type="checkbox" v-model="logUseRegex" @change="loadLogLines(false)">启用正则</label>',
    '              <label>正则<input class="log-re" v-model="logPattern" :disabled="!logUseRegex" @input="queueLogFilter" placeholder="Exception|Error"></label>',
    '              <label>排序<select v-model="logOrder" @change="loadLogLines(false)"><option value="asc">升序</option><option value="desc">倒序</option></select></label>',
    '              <label class="log-report">历史报告<select v-model="selectedReportId" @change="openReport" :disabled="analysisBusy"><option value="">选择已保存的报告</option><option v-for="report in logReports" :key="report.id" :value="String(report.id)">{{ report.created_at }} · {{ report.model }}</option></select></label>',
    '              <div class="settings-actions"><button class="copy-button" @click="showRegexPreview=!showRegexPreview">正则测试</button><button class="copy-button" @click="exportLog" :disabled="logsLoading">导出过滤结果</button><button class="copy-button" @click="openAnalysis">AI 分析</button></div>',
    '            </div>',
    '          </div>',
    '          <regex-preview v-if="showRegexPreview" :initial-pattern="logPattern || \'Exception|Error\'" :initial-text="logRows.slice(0,30).map(row=>row.text).join(\'\\n\')"></regex-preview>',
    '          <p role="status">{{ logsLoading ? "查询中…" : "匹配 " + logTotal + " 行，已加载 " + logRows.length + " 行" }}</p>',
    '          <div class="log-viewer"><div v-for="row in logRows" :key="row.line_no" class="log-line" :class="\'level-\'+(row.level || \'UNKNOWN\')"><span class="log-line-no">{{ row.line_no }}</span><span class="log-line-level">{{ row.level || "—" }}</span><span class="log-line-text" :title="row.text">{{ row.text }}</span></div></div>',
    '          <p v-if="!logsLoading && !logRows.length" class="placeholder dim">没有符合过滤条件的日志行</p><button v-if="logRows.length<logTotal" class="copy-button" :disabled="logsLoading" @click="loadLogLines(true)">加载更多（+500）</button>',
    '          <aside v-if="analysisOpen" class="analysis-drawer" aria-label="日志 AI 分析报告"><div class="analysis-head"><h2>日志 AI 分析</h2><button class="copy-button" @click="closeAnalysis">关闭分析</button></div>',
    '            <p class="placeholder dim">开始后会向已启用的模型发送日志摘要和按需读取的有界片段，不发送日志全文；付费模型按平台计费。</p>',
    '            <label class="analysis-focus">重点关注<input v-model="analysisFocus" maxlength="1000" :disabled="analysisBusy" placeholder="可选：连接超时、错误激增等"></label>',
    '            <div class="settings-actions"><button class="copy-button" :disabled="analysisBusy" @click="startAnalysis">{{ analysisBusy ? "分析中…" : "开始分析" }}</button><button v-if="analysisBusy" class="copy-button" @click="analysisAbort.abort()">停止分析</button></div>',
    '            <p v-if="analysisBusy" role="status">正在检索证据并生成报告…</p><p v-if="analysisSaved" role="status">报告已存历史</p>',
    '            <p v-if="analysisError" class="regex-error" role="alert">{{ analysisError }} <a href="#/settings">前往模型设置</a></p>',
    '            <details v-for="(step,i) in analysisSteps" :key="i" class="trace-card" open><summary>{{ i+1 }} · {{ step.tool }}</summary><pre>{{ JSON.stringify(step.args) }}</pre><p>{{ step.result }}</p></details>',
    '            <article class="markdown-body analysis-report" v-html="analysisHtml"></article>',
    '          </aside>',
    '        </template>',
    '      </template>',
    '    </section>',
    '    <section v-else-if="page === \'codegen\'" class="codegen-page">',
    '      <h1>脚本工坊</h1><p class="placeholder dim">检索本地知识生成脚本；执行前请审阅并在测试环境验证。</p>',
    '      <form class="settings-form" @submit.prevent="generateScript(false)">',
    '        <label>脚本需求<textarea v-model="codegenForm.requirement" required :disabled="codegenBusy" rows="3" placeholder="例如：每天凌晨 2 点打包 /var/log/nginx 目录为 tgz，保留最近 7 天"></textarea></label>',
    '        <label>发行版<select v-model="codegenForm.distro" :disabled="codegenBusy"><option value="">不指定</option><option>CentOS</option><option>Ubuntu</option><option>Debian</option><option>其他</option></select></label>',
    '        <label>补充说明<textarea v-model="codegenForm.notes" :disabled="codegenBusy" rows="2"></textarea></label>',
    '        <button class="copy-button" :disabled="codegenBusy" type="submit">{{ codegenBusy ? "生成中…" : "生成脚本" }}</button>',
    '        <button v-if="codegenBusy" class="copy-button" type="button" @click="codegenAbort.abort()">停止</button>',
    '      </form>',
    '      <section v-if="codegenResult && codegenResult.need_clarification" class="clarification">',
    '        <h2>需要补充信息</h2><form class="settings-form" @submit.prevent="generateScript(true)">',
    '          <label v-for="(q,i) in codegenResult.questions" :key="i">{{ q }}<input required v-model="clarificationAnswers[i]" :disabled="codegenBusy"></label>',
    '          <button class="copy-button" type="submit" :disabled="codegenBusy">补充并重新生成</button>',
    '        </form>',
    '      </section>',
    '      <section v-else-if="codegenResult || codegenBusy">',
    "        <h2>生成过程</h2>",
    '        <p v-if="codegenBusy" class="placeholder dim" role="status">{{ codegenPhaseText }}</p>',
    '        <template v-if="codegenBusy">',
    '          <details v-for="(step,i) in codegenLiveSteps" :key="i" class="trace-card" open><summary>{{ i + 1 }} · {{ step.tool }}</summary><pre>{{ JSON.stringify(step.args) }}</pre><p>{{ step.result_summary }}</p></details>',
    "        </template>",
    '        <template v-else>',
    '          <p v-if="!codegenResult.steps || !codegenResult.steps.length" class="placeholder dim">直接生成</p>',
    '          <details v-for="(step,i) in codegenResult.steps" :key="i" class="trace-card"><summary>{{ i + 1 }} · {{ step.tool }}</summary><pre>{{ JSON.stringify(step.args) }}</pre><p>{{ step.result_summary }}</p></details>',
    "        </template>",
    '        <div class="codegen-output" :style="gridPaneStyle(\'codegen\')"><section><div class="settings-actions"><button class="copy-button" @click="copyScript">复制脚本</button><button class="copy-button" @click="downloadScript">下载 .sh</button></div><pre class="script-source">{{ codegenResult.script }}</pre></section>',
    '          <div class="pane-splitter" title="拖拽调整宽度" @mousedown="startPaneDrag($event, \'codegen\')"></div>',
    '          <section><h2>逐段解读</h2><article v-for="(part,i) in codegenResult.explanation" :key="i" class="trace-card"><h3><span class="line-badge">{{ part.lines }}</span> {{ part.title }}</h3><p>{{ part.detail }}</p></article>',
    '            <div class="script-warnings"><p v-for="(warning,i) in codegenResult.warnings" :key="i">⚠ {{ warning }}</p></div><p class="script-usage">{{ codegenResult.usage }}</p>',
    '          </section></div>',
    '      </section>',
    '      <h2>生成历史</h2><p v-if="!codegenHistory.length" class="placeholder dim">暂无生成记录</p>',
    '      <button v-for="item in codegenHistory" :key="item.id" class="history-item" :disabled="codegenBusy" @click="openCodegenHistory(item)">{{ item.requirement }} · {{ item.model }} · {{ item.created_at }}</button>',
    '    </section>',
    '    <section v-else-if="page === \'assistant\'" class="assistant-page">',
    '      <header class="page-header">',
    "        <div>",
    "          <h1>运维助手</h1>",
    '          <p>基于本地知识库（命令 / 配置 / 脚本历史）回答；回答中的来源可点击跳转</p>',
    "        </div>",
    '        <span class="result-count">模型推断，请以官方文档为准</span>',
    "      </header>",
    '      <div class="asst-layout" :style="gridPaneStyle(\'asst\')">',
    '        <aside class="asst-sessions" aria-label="会话列表">',
    '          <button class="copy-button" type="button" @click="newAsstSession" :disabled="asstBusy">＋ 新建对话</button>',
    '          <p v-if="!asstSessions.length" class="empty-state">暂无历史会话</p>',
    '          <div v-for="s in asstSessions" :key="s.id" class="asst-session-item">',
    '            <button type="button" class="history-item" :class="{ active: asstSessionId === s.id }" @click="openAsstSession(s)">',
    "              <strong>{{ s.title }}</strong>",
    '              <span class="wb-meta">{{ s.updated_at }}</span>',
    "            </button>",
    '            <button v-if="pendingDeleteAsstId === s.id" class="copy-button danger-button asst-del" type="button" @click="deleteAsstSession(s)" :disabled="asstBusy">确认</button>',
    '            <button v-else class="copy-button asst-del" type="button" @click="pendingDeleteAsstId = s.id" :disabled="asstBusy">删除</button>',
    "          </div>",
    "        </aside>",
    '        <div class="pane-splitter" title="拖拽调整宽度" @mousedown="startPaneDrag($event, \'asst\')"></div>',
    '        <section class="asst-chat" aria-label="对话消息流">',
    '          <div class="asst-messages">',
    '            <div v-for="m in asstMessages" :key="m.key" :class="m.role === \'user\' ? \'asst-user\' : \'asst-item\'">',
    '              <div v-if="m.role === \'tool\'" class="asst-tool">',
    '                <span class="asst-tool-name">{{ m.tool || "工具" }}</span>',
    "                <code>{{ JSON.stringify(m.args) }}</code>",
    "                <p>{{ m.result }}</p>",
    "              </div>",
    '              <div v-else-if="m.role === \'user\'" class="asst-bubble-user">{{ m.content }}</div>',
    '              <template v-else>',
    '                <div v-for="(t,i) in m.tools" :key="\'t\'+i" class="asst-tool">',
    '                  <span class="asst-tool-name">{{ t.tool }}</span>',
    "                  <code>{{ JSON.stringify(t.args) }}</code>",
    "                  <p>{{ t.result }}</p>",
    "                </div>",
    '                <article v-if="m.content" class="markdown-body asst-bubble-bot" v-html="assistantMarkdown(m.content)"></article>',
    "              </template>",
    "            </div>",
    '            <p v-if="!asstMessages.length" class="empty-state">问一个运维问题，例如：nginx 怎么平滑重载？<br>助手只依据本地知识库检索结果回答，检索不到会明说；配置工坊中开启共享的配置可被引用。</p>',
    "          </div>",
    '          <p v-if="asstError" class="regex-error" role="alert">{{ asstError }} <a href="#/settings">前往模型设置</a></p>',
    '          <form class="asst-composer" @submit.prevent="sendAsstMessage">',
    '            <textarea v-model="asstInput" rows="2" :disabled="asstBusy" placeholder="输入运维问题，Enter 发送" @keydown.enter.exact.prevent="askKeydown"></textarea>',
    '            <button class="copy-button" type="submit" :disabled="asstBusy || !asstInput.trim()">{{ asstBusy ? "回答中…" : "发送" }}</button>',
    '            <button v-if="asstBusy" class="copy-button" type="button" @click="asstAbort.abort()">停止</button>',
    "          </form>",
    "        </section>",
    "      </div>",
    "    </section>",
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
