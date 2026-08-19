/**
 * 主应用模块
 * 处理页面路由、全局状态和通用功能
 */

const App = {
    currentPage: 'chat',
    refreshInterval: null,
    
    /**
     * 初始化应用
     */
    init() {
        this.bindEvents();
        this.initModules();
        this.loadInitialData();
    },
    
    /**
     * 绑定事件
     */
    bindEvents() {
        // 侧边栏导航
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const page = item.dataset.page;
                if (page) {
                    this.navigateTo(page);
                }
            });
        });
        
        // 侧边栏折叠（持久化）
        const sidebarToggle = document.getElementById('sidebarToggle');
        if (sidebarToggle) {
            const sidebarSaved = localStorage.getItem('sidebarCollapsed') === '1';
            if (sidebarSaved) document.getElementById('sidebar').classList.add('collapsed');
            sidebarToggle.addEventListener('click', () => {
                const el = document.getElementById('sidebar');
                el.classList.toggle('collapsed');
                localStorage.setItem('sidebarCollapsed', el.classList.contains('collapsed') ? '1' : '0');
            });
        }
        
        // 主题切换（light → dark → system 三态循环）
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            const THEMES = ['light', 'dark', 'system'];
            const savedTheme = localStorage.getItem('theme') || 'light';

            const applyTheme = (theme) => {
                const resolve = () => {
                    const resolved = theme === 'system'
                        ? (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
                        : theme;
                    document.documentElement.setAttribute('data-theme', resolved);
                };
                resolve();

                // 先清理旧的监听，避免泄漏；仅 system 主题时重新注册
                if (this._themeMqHandler) {
                    if (window.matchMedia) {
                        matchMedia('(prefers-color-scheme: dark)').removeEventListener('change', this._themeMqHandler);
                    }
                    this._themeMqHandler = null;
                }
                if (theme === 'system' && window.matchMedia) {
                    const mq = matchMedia('(prefers-color-scheme: dark)');
                    this._themeMqHandler = () => {
                        if (localStorage.getItem('theme') === 'system') resolve();
                    };
                    mq.addEventListener('change', this._themeMqHandler);
                }

                const labels = { light: '浅色', dark: '深色', system: '系统' };
                const labelEl = document.getElementById('themeToggleLabel');
                if (labelEl) labelEl.textContent = labels[theme];
                themeToggle.title = `主题：${labels[theme]}（点击切换）`;
            };

            applyTheme(savedTheme);

            themeToggle.addEventListener('click', () => {
                const current = localStorage.getItem('theme') || 'light';
                const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
                localStorage.setItem('theme', next);
                applyTheme(next);
            });
        }
        
        // 模态框关闭
        const modalClose = document.getElementById('modalClose');
        const modalOverlay = document.querySelector('.modal-overlay');
        const confirmCancel = document.getElementById('confirmCancel');
        
        [modalClose, modalOverlay, confirmCancel].forEach(el => {
            if (el) {
                el.addEventListener('click', () => this.closeModal());
            }
        });
        
        // 监控页面刷新
        const refreshMonitorBtn = document.getElementById('refreshMonitorBtn');
        if (refreshMonitorBtn) {
            refreshMonitorBtn.addEventListener('click', () => this.loadMonitorData());
        }
        
        // 审计日志刷新
        const refreshAuditBtn = document.getElementById('refreshAuditBtn');
        if (refreshAuditBtn) {
            refreshAuditBtn.addEventListener('click', () => this.loadAuditLogs());
        }
        
        // 清除审计日志
        const clearAuditBtn = document.getElementById('clearAuditBtn');
        if (clearAuditBtn) {
            clearAuditBtn.addEventListener('click', () => this.clearAuditLogs());
        }
        
        // 导出审计日志
        const exportAuditCsvBtn = document.getElementById('exportAuditCsvBtn');
        if (exportAuditCsvBtn) {
            exportAuditCsvBtn.addEventListener('click', () => this.exportAuditLogs('csv'));
        }
        const exportAuditJsonBtn = document.getElementById('exportAuditJsonBtn');
        if (exportAuditJsonBtn) {
            exportAuditJsonBtn.addEventListener('click', () => this.exportAuditLogs('json'));
        }
        
        // 审计日志筛选
        const auditStageFilter = document.getElementById('auditStageFilter');
        if (auditStageFilter) {
            auditStageFilter.addEventListener('change', () => this.loadAuditLogs());
        }
        
        // 审计日志搜索（防抖）
        const auditSearch = document.getElementById('auditSearch');
        if (auditSearch) {
            auditSearch.addEventListener('input', () => {
                clearTimeout(this._auditSearchTimer);
                this._auditSearchTimer = setTimeout(() => this.loadAuditLogs(), 300);
            });
            auditSearch.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    auditSearch.value = '';
                    this.loadAuditLogs();
                }
            });
        }
        
        // 工具管理刷新
        const refreshToolsBtn = document.getElementById('refreshToolsBtn');
        if (refreshToolsBtn) {
            refreshToolsBtn.addEventListener('click', () => this.loadTools());
        }

        // 工具排序切换
        const toolsSort = document.getElementById('toolsSort');
        if (toolsSort) {
            toolsSort.addEventListener('change', () => this.renderTools());
        }
        
        // 创建工具表单
        const createToolBtn = document.getElementById('createToolBtn');
        if (createToolBtn) {
            createToolBtn.addEventListener('click', () => {
                document.getElementById('createToolForm').style.display = 'block';
            });
        }
        
        const cancelToolBtn = document.getElementById('cancelToolBtn');
        if (cancelToolBtn) {
            cancelToolBtn.addEventListener('click', () => {
                document.getElementById('createToolForm').style.display = 'none';
                this._clearToolForm();
            });
        }
        
        const saveToolBtn = document.getElementById('saveToolBtn');
        if (saveToolBtn) {
            saveToolBtn.addEventListener('click', () => this.createCustomTool());
        }
    },
    
    /**
     * 初始化模块
     */
    initModules() {
        Chat.init();
        Settings.init();
    },
    
    /**
     * 加载初始数据
     */
    loadInitialData() {
        this.loadMonitorData();
        this.loadTools();
    },
    
    /**
     * 页面导航
     */
    navigateTo(page) {
        // 更新导航状态
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === page);
        });
        
        // 切换页面
        document.querySelectorAll('.page').forEach(p => {
            p.classList.toggle('active', p.id === `page-${page}`);
        });
        
        this.currentPage = page;
        
        // 根据页面加载数据
        switch (page) {
            case 'monitor':
                this.loadMonitorData();
                this.startAutoRefresh();
                break;
            case 'audit':
                this.stopAutoRefresh();
                this.loadAuditLogs();
                break;
            case 'tools':
                this.stopAutoRefresh();
                this.loadTools();
                break;
            default:
                this.stopAutoRefresh();
                break;
        }
    },
    
    /**
     * 加载监控数据
     */
    async loadMonitorData() {
        try {
            const result = await API.getStatus();
            
            if (result.success) {
                const { cpu_percent, memory_percent, disk_percent, tools_count } = result.data;
                
                // 更新仪表盘
                this.updateGauge('cpuGauge', cpu_percent);
                this.updateGauge('memoryGauge', memory_percent);
                this.updateGauge('diskGauge', disk_percent);
                
                // 更新工具状态
                const toolStatus = document.getElementById('toolStatus');
                if (toolStatus) {
                    toolStatus.innerHTML = `
                        <span class="status-text">${this.escapeHtml(tools_count)} 个工具已注册</span>
                        <span class="status-dot online"></span>
                    `;
                }
            }
            
        } catch (error) {
            console.error('加载监控数据失败:', error);
        }
    },
    
    /**
     * 更新仪表盘
     */
    updateGauge(gaugeId, value) {
        const gauge = document.getElementById(gaugeId);
        if (!gauge) return;
        
        const percentage = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
        gauge.style.background = `conic-gradient(
            ${percentage > 80 ? 'var(--danger-color)' : percentage > 60 ? 'var(--warning-color)' : 'var(--primary-color)'} ${percentage}%, 
            var(--bg-tertiary) ${percentage}%
        )`;
        
        const valueElement = gauge.querySelector('.gauge-value');
        if (valueElement) {
            valueElement.textContent = `${percentage}%`;
        }
    },
    
    /**
     * 加载审计日志（Trajectory 轨迹视图）
     * 无搜索词时：渲染轨迹卡片列表（横向阶段时间线，可展开详情）
     * 有搜索词时：渲染全文检索命中列表，点击打开对应轨迹详情
     */
    async loadAuditLogs() {
        const timeline = document.getElementById('auditTimeline');
        if (!timeline) return;

        const stageFilter = document.getElementById('auditStageFilter')?.value || '';
        const searchTerm = (document.getElementById('auditSearch')?.value || '').trim();

        if (searchTerm) {
            this._renderAuditSearch(searchTerm, stageFilter, timeline);
            return;
        }

        try {
            const result = await API.getTraces();
            const traces = result.data || [];

            let filtered = traces;
            if (stageFilter) {
                filtered = traces.filter(t => t.stages && t.stages.includes(stageFilter));
            }

            if (!filtered.length) {
                timeline.innerHTML = this.auditEmptyHtml('暂无审计日志');
                return;
            }

            timeline.innerHTML = filtered.map(t => this.trajectoryCardHtml(t)).join('');

            // 卡片头部点击 → 展开/收起轨迹详情
            timeline.querySelectorAll('.trajectory-card').forEach(card => {
                card.querySelector('.trajectory-header').addEventListener('click', () => {
                    this.toggleTrajectory(card);
                });
            });
        } catch (error) {
            console.error('加载审计日志失败:', error);
            timeline.innerHTML = this.auditEmptyHtml('加载失败，请稍后重试');
        }
    },

    /**
     * 轨迹卡片 HTML（头部 + 横向阶段时间线 + 详情容器）
     */
    trajectoryCardHtml(trace) {
        const stages = (trace.stages || []).slice(0, 6);
        const nodes = stages.map(s => `
            <span class="traj-node ${this.escapeHtml(s)}" title="${this.escapeHtml(this.getStageName(s))}">
                <span class="traj-glyph">${this.getStageGlyph(s)}</span>
            </span>
        `).join('');
        const total = trace.stage_count || (trace.stages || []).length;
        const more = total > 6
            ? `<span class="traj-more">+${total - 6}</span>`
            : '';

        return `
            <div class="trajectory-card" data-trace-id="${this.escapeHtml(trace.trace_id)}">
                <div class="trajectory-header">
                    <div class="trajectory-title">
                        <span>${this.escapeHtml(trace.title || trace.trace_id)}</span>
                    </div>
                    <div class="trajectory-meta">
                        <span class="traj-time">${this.formatTime(trace.end_time || trace.start_time)}</span>
                        <span class="traj-count">${total} 阶段</span>
                        <span class="traj-chevron">▾</span>
                    </div>
                </div>
                <div class="trajectory-timeline">
                    <div class="traj-line"></div>
                    ${nodes}
                    ${more}
                </div>
                <div class="trajectory-detail hidden"></div>
            </div>
        `;
    },

    /**
     * 展开/收起轨迹详情（拉取完整阶段时间线）
     */
    async toggleTrajectory(card) {
        const detail = card.querySelector('.trajectory-detail');
        const traceId = card.dataset.traceId;
        if (!detail) return;

        if (card.classList.contains('expanded')) {
            card.classList.remove('expanded');
            detail.classList.add('hidden');
            const chevron = card.querySelector('.traj-chevron');
            if (chevron) chevron.textContent = '▾';
            return;
        }

        card.classList.add('expanded');
        detail.classList.remove('hidden');
        const chevron = card.querySelector('.traj-chevron');
        if (chevron) chevron.textContent = '▴';
        detail.innerHTML = '<div class="audit-empty"><p>加载中...</p></div>';

        try {
            const res = await API.getTraceDetail(traceId);
            const stages = res.data.stages || [];
            detail.innerHTML = stages.map(s => this.trajectoryStageHtml(s)).join('');
        } catch (error) {
            detail.innerHTML = this.auditEmptyHtml('加载失败');
        }
    },

    /**
     * 单个轨迹阶段 HTML（纵向详情）
     */
    trajectoryStageHtml(s) {
        const toolInfo = s.tool_name
            ? `<div class="traj-stage-tool">${this.escapeHtml(s.tool_name)}</div>`
            : '';
        const content = s.content
            ? `<div class="traj-stage-content">${this.escapeHtml(s.content)}</div>`
            : '';
        const params = (s.tool_params && Object.keys(s.tool_params).length)
            ? `<pre class="traj-stage-pre">${this.escapeHtml(JSON.stringify(s.tool_params, null, 2))}</pre>`
            : '';
        const result = s.tool_result
            ? `<pre class="traj-stage-pre">${this.escapeHtml(s.tool_result)}</pre>`
            : '';
        const risk = s.risk_level
            ? `<span class="risk-badge risk-${this.escapeHtml(s.risk_level)}">${this.escapeHtml(this.getRiskLevelName(s.risk_level))}</span>`
            : '';

        return `
            <div class="trajectory-stage">
                <div class="traj-stage-header">
                    <span class="traj-glyph">${this.getStageGlyph(s.stage)}</span>
                    <span class="traj-stage-name">${this.getStageName(s.stage)}</span>
                    ${risk}
                    <span class="traj-stage-time">${this.formatTime(s.timestamp)}</span>
                </div>
                ${toolInfo}
                ${content}
                ${params}
                ${result}
            </div>
        `;
    },

    /**
     * 审计全文检索（命中列表 → 点击打开轨迹详情）
     */
    async _renderAuditSearch(term, stageFilter, timeline) {
        timeline.innerHTML = '<div class="audit-empty"><p>加载中...</p></div>';
        try {
            const res = await API.search(term, 'audit', 50);
            let data = res.data || [];
            if (stageFilter) data = data.filter(l => l.stage === stageFilter);

            if (!data.length) {
                timeline.innerHTML = this.auditEmptyHtml('无匹配结果');
                return;
            }

            timeline.innerHTML = `
                <div class="search-summary">找到 ${data.length} 条命中（点击查看轨迹）</div>
                ${data.map(l => `
                    <div class="search-audit-hit" data-trace-id="${this.escapeHtml(l.trace_id)}">
                        <span class="audit-stage-badge ${this.escapeHtml(l.stage)}">
                            <span class="traj-glyph">${this.getStageGlyph(l.stage)}</span> ${this.escapeHtml(this.getStageName(l.stage))}
                        </span>
                        <span class="search-hit-preview">${this.escapeHtml(l.content)}</span>
                        <span class="traj-stage-time">${this.formatTime(l.timestamp)}</span>
                    </div>
                `).join('')}
            `;

            timeline.querySelectorAll('.search-audit-hit').forEach(el => {
                el.addEventListener('click', () => this.openSearchTrace(el.dataset.traceId, timeline));
            });
        } catch (error) {
            console.error('审计检索失败:', error);
            timeline.innerHTML = this.auditEmptyHtml('搜索失败');
        }
    },

    /**
     * 从搜索结果打开指定轨迹（在列表顶部插入并展开）
     */
    async openSearchTrace(traceId, timeline) {
        try {
            const res = await API.getTraceDetail(traceId);
            const stages = res.data.stages || [];
            const title = stages[0]?.content || traceId;

            const card = document.createElement('div');
            card.className = 'trajectory-card expanded';
            card.dataset.traceId = traceId;
            card.innerHTML = `
                <div class="trajectory-header">
                    <div class="trajectory-title">
                        <span>${this.escapeHtml(title)}</span>
                    </div>
                    <div class="trajectory-meta">
                        <button class="btn btn-secondary btn-xs" id="closeSearchTrace">
                            返回搜索结果
                        </button>
                    </div>
                </div>
                <div class="trajectory-detail">${stages.map(s => this.trajectoryStageHtml(s)).join('')}</div>
            `;

            const existing = timeline.querySelector(`.trajectory-card[data-trace-id="${traceId}"]`);
            if (existing) existing.remove();
            timeline.prepend(card);

            card.querySelector('#closeSearchTrace').addEventListener('click', () => {
                card.remove();
                this.loadAuditLogs();
            });
        } catch (error) {
            console.error('打开轨迹失败:', error);
        }
    },

    /**
     * 审计空状态 HTML
     */
    auditEmptyHtml(text) {
        return `
            <div class="audit-empty">
                <p>${this.escapeHtml(text)}</p>
            </div>
        `;
    },

    /**
     * 转义HTML
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    },
    
    /**
     * 清除审计日志
     */
    async clearAuditLogs() {
        try {
            await API.clearTraces();
            this.loadAuditLogs();
            this.showNotification('审计日志已清除', 'success');
            
        } catch (error) {
            console.error('清除审计日志失败:', error);
            this.showNotification('清除审计日志失败', 'error');
        }
    },

    /**
     * 导出审计日志（CSV / JSON 文件下载）
     */
    async exportAuditLogs(format = 'csv') {
        const btn = format === 'csv'
            ? document.getElementById('exportAuditCsvBtn')
            : document.getElementById('exportAuditJsonBtn');
        if (btn) btn.disabled = true;
        try {
            const stageFilter = document.getElementById('auditStageFilter')?.value || '';
            const params = {};
            if (stageFilter) params.stage = stageFilter;
            const result = await API.exportAuditLogs(format, params);
            if (result && result.count === 0) {
                this.showNotification('没有可导出的审计数据', 'warning');
                return;
            }
            this.showNotification(`审计日志已导出（${format.toUpperCase()}）`, 'success');
        } catch (error) {
            console.error('导出审计日志失败:', error);
            this.showNotification('导出审计日志失败', 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    },
    
    /**
     * 加载工具列表
     */
    async loadTools() {
        try {
            const result = await API.getTools();
            this._tools = (result.data || []);
            this.renderTools();
        } catch (error) {
            console.error('加载工具列表失败:', error);
            const container = document.getElementById('toolsContainer');
            if (container) {
                container.innerHTML = `
                    <div class="tools-loading">
                        <span>工具列表加载失败</span>
                    </div>
                `;
            }
            this.showNotification('加载工具列表失败', 'error');
        }
    },

    /**
     * 渲染工具卡片（应用当前排序）
     */
    renderTools() {
        const container = document.getElementById('toolsContainer');
        const list = this._tools || [];

        if (list.length === 0) {
            container.innerHTML = `
                <div class="tools-loading">
                    <span>暂无注册工具</span>
                </div>
            `;
            return;
        }

        const sorted = this.sortTools(list);
        container.innerHTML = `
            <div class="tools-grid">
                ${sorted.map(tool => this.toolCardHtml(tool)).join('')}
            </div>
        `;

        // 绑定删除按钮
        container.querySelectorAll('.tool-delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const toolName = btn.dataset.name;
                this.deleteCustomTool(toolName);
            });
        });
    },

    /**
     * 单张工具卡片 HTML
     */
    toolCardHtml(tool) {
        const created = tool.is_custom && tool.created_at
            ? `<span class="tool-created">创建于 ${this.escapeHtml(tool.created_at.slice(0, 10))}</span>`
            : '';
        return `
            <div class="tool-card">
                <div class="tool-card-header">
                    <span class="tool-card-title">${this.escapeHtml(tool.name)}</span>
                    <div>
                        ${tool.is_custom ? '<span class="tool-badge custom">自定义</span>' : ''}
                        <span class="tool-badge risk-${this.escapeHtml(tool.risk_level)}">${this.escapeHtml(this.getRiskLevelName(tool.risk_level))}</span>
                    </div>
                </div>
                <div class="tool-card-description">${this.escapeHtml(tool.description)}</div>
                <div class="tool-card-footer">
                    <span>${this.escapeHtml(tool.category)}</span>
                    <span class="footer-risk risk-${this.escapeHtml(tool.risk_level)}">${tool.requires_approval ? '需要审批' : '自动执行'}</span>
                    <span class="footer-right">
                        ${created}
                        ${tool.is_custom ? `<button class="tool-delete-btn" data-name="${this.escapeHtml(tool.name)}">删除</button>` : ''}
                    </span>
                </div>
            </div>
        `;
    },

    /**
     * 按当前排序方式排序工具列表
     */
    sortTools(list) {
        const key = document.getElementById('toolsSort')?.value || 'default';
        const arr = [...list];

        if (key === 'name-asc' || key === 'name-desc') {
            const dir = key === 'name-asc' ? 1 : -1;
            arr.sort((a, b) => dir * (a.name || '').localeCompare(b.name || ''));
        } else if (key === 'date-desc' || key === 'date-asc') {
            const dir = key === 'date-desc' ? 1 : -1;
            arr.sort((a, b) => {
                const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
                const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
                return dir * (ta - tb);
            });
        }

        return arr;
    },
    
    async createCustomTool() {
        const name = document.getElementById('toolName').value.trim();
        const description = document.getElementById('toolDescription').value.trim();
        const riskLevel = document.getElementById('toolRiskLevel').value;
        const commandType = document.getElementById('toolCommandType').value;
        const commandTemplate = document.getElementById('toolCommandTemplate').value.trim();
        const paramsStr = document.getElementById('toolParameters').value.trim();
        
        if (!name) { this.showNotification('请输入工具名称', 'warning'); return; }
        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) { this.showNotification('工具名称只能包含字母、数字和下划线，且必须以字母或下划线开头', 'warning'); return; }
        if (!description) { this.showNotification('请输入工具描述', 'warning'); return; }
        if (!commandTemplate) { this.showNotification('请输入命令模板', 'warning'); return; }
        
        let parameters = null;
        if (paramsStr) {
            try { parameters = JSON.parse(paramsStr); } 
            catch(e) { this.showNotification('参数定义JSON格式错误', 'warning'); return; }
        }
        
        try {
            const result = await API.post('/api/custom-tools/', {
                name, description, risk_level: riskLevel,
                command_type: commandType, command_template: commandTemplate,
                parameters, category: 'custom'
            });
            
            if (result.success) {
                this.showNotification(`工具 ${name} 创建成功`, 'success');
                document.getElementById('createToolForm').style.display = 'none';
                this._clearToolForm();
                this.loadTools();
            } else {
                this.showNotification('创建失败: ' + (result.detail || result.message), 'error');
            }
        } catch (error) {
            this.showNotification('创建工具失败: ' + error.message, 'error');
        }
    },
    
    async deleteCustomTool(toolName) {
        if (!confirm(`确定要删除自定义工具 "${toolName}" 吗？`)) return;
        
        try {
            // 先获取工具ID
            const toolsResult = await API.getTools();
            const tool = toolsResult.data.find(t => t.name === toolName && t.is_custom);
            if (!tool) { this.showNotification('工具不存在', 'error'); return; }
            
            const result = await API.delete(`/api/custom-tools/${tool.id}`);
            if (result.success) {
                this.showNotification(`工具 ${toolName} 已删除`, 'success');
                this.loadTools();
            } else {
                this.showNotification('删除失败', 'error');
            }
        } catch (error) {
            this.showNotification('删除工具失败: ' + error.message, 'error');
        }
    },
    
    _clearToolForm() {
        ['toolName','toolDescription','toolParameters','toolCommandTemplate'].forEach(id => {
            document.getElementById(id).value = '';
        });
        document.getElementById('toolRiskLevel').value = 'low';
        document.getElementById('toolCommandType').value = 'shell';
    },
    
    /**
     * 开始自动刷新
     */
    startAutoRefresh() {
        this.stopAutoRefresh();
        this.refreshInterval = setInterval(() => {
            if (this.currentPage === 'monitor') {
                this.loadMonitorData();
            }
        }, 5000);
    },
    
    /**
     * 停止自动刷新
     */
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    },
    
    /**
     * 显示通知
     */
    showNotification(message, type = 'info') {
        const container = document.getElementById('notificationContainer');
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;

        const labels = {
            success: '成功',
            error: '失败',
            warning: '警告',
            info: '信息',
        };

        notification.innerHTML = `
            <span class="notification-dot ${type}"></span>
            <span class="notification-text">${this.escapeHtml(message)}</span>
            <button class="notification-close" onclick="this.parentElement.remove()">
                <span>×</span>
            </button>
        `;
        
        container.appendChild(notification);
        
        // 自动关闭
        setTimeout(() => {
            notification.remove();
        }, 5000);
    },
    
    /**
     * 显示确认对话框
     */
    showConfirm(message, details = '', onConfirm) {
        const modal = document.getElementById('confirmModal');
        const confirmMessage = document.getElementById('confirmMessage');
        const confirmDetails = document.getElementById('confirmDetails');
        const confirmOk = document.getElementById('confirmOk');
        
        confirmMessage.textContent = message;
        confirmDetails.textContent = details;
        
        modal.classList.add('active');
        
        // 移除旧的事件监听器
        const newConfirmOk = confirmOk.cloneNode(true);
        confirmOk.parentNode.replaceChild(newConfirmOk, confirmOk);
        
        // 添加新的事件监听器
        newConfirmOk.addEventListener('click', () => {
            this.closeModal();
            onConfirm?.();
        });
    },
    
    /**
     * 关闭模态框
     */
    closeModal() {
        const modal = document.getElementById('confirmModal');
        modal.classList.remove('active');
    },
    
    /**
     * 获取阶段图标
     */
    getStageGlyph(stage) {
        const glyphs = {
            user_input: '问',
            environment_perception: '察',
            llm_reasoning: '思',
            safety_check: '护',
            execution: '行',
            response: '答',
        };
        return glyphs[stage] || '步';
    },
    
    /**
     * 获取阶段名称
     */
    getStageName(stage) {
        const names = {
            user_input: '用户输入',
            environment_perception: '环境感知',
            llm_reasoning: 'LLM推理',
            safety_check: '安全检查',
            execution: '执行',
            response: '响应',
        };
        return names[stage] || stage;
    },
    
    /**
     * 获取风险等级名称
     */
    getRiskLevelName(level) {
        const names = {
            low: '低风险',
            medium: '中风险',
            high: '高风险',
        };
        return names[level] || level;
    },
    
    /**
     * 格式化时间
     */
    formatTime(timestamp) {
        if (!timestamp) return '';
        
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) return '';
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) {
            return '刚刚';
        } else if (diff < 3600000) {
            return `${Math.floor(diff / 60000)} 分钟前`;
        } else if (diff < 86400000) {
            return `${Math.floor(diff / 3600000)} 小时前`;
        } else {
            return date.toLocaleString('zh-CN');
        }
    },
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});

// 导出App对象
window.App = App;
