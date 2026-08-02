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
        
        // 侧边栏折叠
        const sidebarToggle = document.getElementById('sidebarToggle');
        if (sidebarToggle) {
            sidebarToggle.addEventListener('click', () => {
                document.getElementById('sidebar').classList.toggle('collapsed');
            });
        }
        
        // 主题切换
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            const savedTheme = localStorage.getItem('theme') || 'light';
            if (savedTheme === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
                themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
            }
            themeToggle.addEventListener('click', () => {
                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                const newTheme = isDark ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', newTheme);
                localStorage.setItem('theme', newTheme);
                themeToggle.innerHTML = isDark ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';
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
        
        // 审计日志筛选
        const auditStageFilter = document.getElementById('auditStageFilter');
        if (auditStageFilter) {
            auditStageFilter.addEventListener('change', () => this.loadAuditLogs());
        }
        
        // 工具管理刷新
        const refreshToolsBtn = document.getElementById('refreshToolsBtn');
        if (refreshToolsBtn) {
            refreshToolsBtn.addEventListener('click', () => this.loadTools());
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
                this.loadAuditLogs();
                break;
            case 'tools':
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
                        <span class="status-text">${tools_count} 个工具已注册</span>
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
        
        const percentage = Math.round(value);
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
     * 加载审计日志
     */
    async loadAuditLogs() {
        try {
            const stageFilter = document.getElementById('auditStageFilter').value;
            const params = {};
            
            if (stageFilter) {
                params.stage = stageFilter;
            }
            
            const result = await API.getAuditLogs(params);
            
            const timeline = document.getElementById('auditTimeline');
            
            if (result.success && result.data.length > 0) {
                timeline.innerHTML = result.data.map(log => `
                    <div class="audit-item">
                        <div class="audit-icon ${log.stage}">
                            <i class="fas ${this.getStageIcon(log.stage)}"></i>
                        </div>
                        <div class="audit-content">
                            <div class="audit-header">
                                <span class="audit-stage">${this.getStageName(log.stage)}</span>
                                <span class="audit-time">${this.formatTime(log.timestamp)}</span>
                            </div>
                            <div class="audit-text">${log.content}</div>
                        </div>
                    </div>
                `).join('');
            } else {
                timeline.innerHTML = `
                    <div class="audit-empty">
                        <i class="fas fa-history"></i>
                        <p>暂无审计日志</p>
                    </div>
                `;
            }
            
        } catch (error) {
            console.error('加载审计日志失败:', error);
        }
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
     * 加载工具列表
     */
    async loadTools() {
        try {
            const result = await API.getTools();
            
            const container = document.getElementById('toolsContainer');
            
            if (result.success && result.data.length > 0) {
                container.innerHTML = `
                    <div class="tools-grid">
                        ${result.data.map(tool => `
                            <div class="tool-card">
                                <div class="tool-card-header">
                                    <span class="tool-card-title">${tool.name}</span>
                                    <div>
                                        ${tool.is_custom ? '<span class="tool-badge custom">自定义</span>' : ''}
                                        <span class="tool-badge ${tool.risk_level}">${this.getRiskLevelName(tool.risk_level)}</span>
                                    </div>
                                </div>
                                <div class="tool-card-description">${tool.description}</div>
                                <div class="tool-card-footer">
                                    <span><i class="fas fa-folder"></i> ${tool.category}</span>
                                    <span>${tool.requires_approval ? '<i class="fas fa-lock"></i> 需要审批' : '<i class="fas fa-unlock"></i> 自动执行'}</span>
                                    ${tool.is_custom ? `<button class="tool-delete-btn" data-name="${tool.name}"><i class="fas fa-trash"></i> 删除</button>` : ''}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `;
                
                // 绑定删除按钮
                container.querySelectorAll('.tool-delete-btn').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        const toolName = btn.dataset.name;
                        this.deleteCustomTool(toolName);
                    });
                });
            } else {
                container.innerHTML = `
                    <div class="tools-loading">
                        <i class="fas fa-tools"></i>
                        <span>暂无注册工具</span>
                    </div>
                `;
            }
            
        } catch (error) {
            console.error('加载工具列表失败:', error);
        }
    },
    
    async createCustomTool() {
        const name = document.getElementById('toolName').value.trim();
        const description = document.getElementById('toolDescription').value.trim();
        const riskLevel = document.getElementById('toolRiskLevel').value;
        const commandType = document.getElementById('toolCommandType').value;
        const commandTemplate = document.getElementById('toolCommandTemplate').value.trim();
        const paramsStr = document.getElementById('toolParameters').value.trim();
        
        if (!name) { this.showNotification('请输入工具名称', 'warning'); return; }
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
        
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-times-circle',
            warning: 'fa-exclamation-circle',
            info: 'fa-info-circle',
        };
        
        notification.innerHTML = `
            <span class="notification-icon">
                <i class="fas ${icons[type] || icons.info}"></i>
            </span>
            <span class="notification-text">${message}</span>
            <button class="notification-close" onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
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
    getStageIcon(stage) {
        const icons = {
            user_input: 'fa-user',
            environment_perception: 'fa-eye',
            llm_reasoning: 'fa-brain',
            safety_check: 'fa-shield-alt',
            execution: 'fa-play',
            response: 'fa-reply',
        };
        return icons[stage] || 'fa-circle';
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
