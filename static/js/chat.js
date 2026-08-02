/**
 * 对话功能模块
 * 处理聊天界面的所有交互
 */

const Chat = {
    sessionId: null,
    isProcessing: false,
    conversations: [],
    
    /**
     * 初始化对话模块
     */
    init() {
        this.bindEvents();
        this.loadConversations();
    },
    
    /**
     * 绑定事件
     */
    bindEvents() {
        // 发送按钮
        const sendBtn = document.getElementById('sendBtn');
        if (sendBtn) {
            sendBtn.addEventListener('click', () => this.sendMessage());
        }
        
        // 输入框
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
            
            // 自动调整高度
            chatInput.addEventListener('input', () => {
                chatInput.style.height = 'auto';
                chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
            });
        }
        
        // 新对话按钮
        const newChatBtn = document.getElementById('newChatBtn');
        if (newChatBtn) {
            newChatBtn.addEventListener('click', () => this.createConversation());
        }
        
        // 清空按钮
        const clearChatBtn = document.getElementById('clearChatBtn');
        if (clearChatBtn) {
            clearChatBtn.addEventListener('click', () => this.clearConversation());
        }
        
        // 对话列表侧边栏切换
        const convSidebarToggle = document.getElementById('convSidebarToggle');
        if (convSidebarToggle) {
            convSidebarToggle.addEventListener('click', () => {
                document.getElementById('conversationSidebar').classList.toggle('collapsed');
            });
        }
        
        // 示例按钮
        document.querySelectorAll('.example-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const query = btn.dataset.query;
                if (query) {
                    document.getElementById('chatInput').value = query;
                    this.sendMessage();
                }
            });
        });
    },
    
    /**
     * 发送消息
     */
    async sendMessage() {
        const input = document.getElementById('chatInput');
        const message = input.value.trim();
        
        if (!message || this.isProcessing) {
            return;
        }
        
        // 清空输入框
        input.value = '';
        input.style.height = 'auto';
        
        // 隐藏欢迎消息
        this.hideWelcome();
        
        // 添加用户消息
        this.addMessage('user', message);
        
        // 显示加载状态
        this.showLoading();
        this.isProcessing = true;
        
        try {
            // 流式发送消息
            let preToolContent = '';   // 工具调用前的AI文字（如"好的，我来查看..."）
            let postToolContent = '';  // 工具调用后的AI总结
            let messageElement = null;
            let sawTools = false;
            
            await API.sendMessageStream(
                message,
                this.sessionId,
                // onChunk
                (chunk) => {
                    if (chunk.type === 'content') {
                        if (!sawTools) {
                            // 工具调用前的内容，暂存不显示
                            preToolContent += chunk.content;
                        } else {
                            // 工具调用后的内容，这是AI的总结，需要显示
                            if (!messageElement) {
                                messageElement = this.addMessage('assistant', '');
                            }
                            postToolContent += chunk.content;
                            this.updateMessage(messageElement, postToolContent);
                        }
                    } else if (chunk.type === 'tool_calls') {
                        sawTools = true;
                        // 如果有工具调用前的AI文字，先显示
                        if (preToolContent && !messageElement) {
                            messageElement = this.addMessage('assistant', preToolContent.trim());
                        }
                        this.showToolCalls(chunk.tool_calls);
                    } else if (chunk.type === 'tool_result') {
                        this.showToolResult(chunk.tool_name, chunk.result);
                    } else if (chunk.type === 'error') {
                        if (!messageElement) {
                            messageElement = this.addMessage('assistant', '');
                        }
                        this.updateMessage(messageElement, this.getErrorMessage(chunk.message));
                    }
                },
                // onDone
                () => {
                    this.hideLoading();
                    this.isProcessing = false;
                },
                // onError
                (error) => {
                    console.error('流式请求失败:', error);
                    this.hideLoading();
                    this.isProcessing = false;
                    this.addMessage('assistant', this.getErrorMessage(error.message || '网络连接失败'));
                }
            );
            
        } catch (error) {
            console.error('发送消息失败:', error);
            this.hideLoading();
            this.isProcessing = false;
            this.addMessage('assistant', '抱歉，发送消息失败。请稍后重试。');
        }
    },
    
    /**
     * 添加消息
     */
    addMessage(role, content) {
        const messagesContainer = document.getElementById('chatMessages');
        
        const messageElement = document.createElement('div');
        messageElement.className = `message ${role}`;
        
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
        
        const contentElement = document.createElement('div');
        contentElement.className = 'message-content';
        
        if (role === 'assistant' && content) {
            contentElement.innerHTML = this.renderMarkdown(content);
        } else {
            contentElement.textContent = content;
        }
        
        messageElement.appendChild(avatar);
        messageElement.appendChild(contentElement);
        
        messagesContainer.appendChild(messageElement);
        
        // 滚动到底部
        this.scrollToBottom();
        
        return messageElement;
    },
    
    /**
     * 更新消息内容
     */
    updateMessage(messageElement, content) {
        const contentElement = messageElement.querySelector('.message-content');
        if (contentElement) {
            contentElement.innerHTML = this.renderMarkdown(content);
            this.scrollToBottom();
        }
    },
    
    /**
     * 显示工具调用
     */
    showToolCalls(toolCalls) {
        const messagesContainer = document.getElementById('chatMessages');
        
        toolCalls.forEach(toolCall => {
            let argsText = '';
            let argsJson = toolCall.function.arguments;
            try {
                const args = JSON.parse(toolCall.function.arguments);
                const entries = Object.entries(args).filter(([k,v]) => v !== '' && v !== undefined);
                if (entries.length > 0) {
                    argsText = entries.map(([k,v]) => `${k}=${v}`).join(', ');
                }
                argsJson = JSON.stringify(args, null, 2);
            } catch(e) {}
            
            const el = document.createElement('details');
            el.className = 'tool-call';
            el.innerHTML = `
                <summary class="tool-call-header">
                    <i class="fas fa-wrench"></i>
                    <span class="tool-name">${toolCall.function.name}</span>
                    ${argsText ? `<span class="tool-args">(${argsText})</span>` : ''}
                </summary>
                <div class="tool-call-body">
                    <pre><code>${this.escapeHtml(argsJson)}</code></pre>
                </div>
            `;
            messagesContainer.appendChild(el);
        });
        
        this.scrollToBottom();
    },
    
    showToolResult(toolName, result) {
        const container = document.getElementById('chatMessages');
        
        let summary = '';
        try {
            // 兼容两种数据格式：{success,data} 或直接 {data}
            const d = result?.result?.data || result?.data || result;
            if (d?.hostname) summary = d.hostname + ' | ' + (d.os||'');
            else if (Array.isArray(d) && d[0]?.mountpoint) summary = d.map(p=>p.mountpoint+': '+p.percent+'%').join(', ');
            else if (d?.virtual_memory) summary = '内存: '+d.virtual_memory.used_gb+'/'+d.virtual_memory.total_gb+'GB ('+d.virtual_memory.percent+'%)';
            else if (d?.logical_cores !== undefined) summary = 'CPU: '+d.logical_cores+'核 | '+(d.average_usage||0).toFixed(1)+'%';
            else if (d?.io_counters) summary = '网络IO: '+(d.io_counters.bytes_recv/1048576).toFixed(1)+'MB';
            else if (result?.success !== undefined) summary = result.success ? '执行成功' : (result.error || '执行完成');
            else summary = '执行完成';
        } catch(e) { summary = '执行完成'; }
        
        const el = document.createElement('details');
        el.className = 'tool-call';
        el.innerHTML = `<summary class="tool-call-header"><i class="fas fa-check-circle" style="color:var(--success-color)"></i><span class="tool-name">${toolName}</span><span class="tool-args">${summary}</span></summary><div class="tool-call-body"><pre><code>${this.escapeHtml(JSON.stringify(result, null, 2))}</code></pre></div>`;
        container.appendChild(el);
        
        this.scrollToBottom();
    },
    
    /**
     * 显示加载状态
     */
    showLoading() {
        const messagesContainer = document.getElementById('chatMessages');
        
        const loadingElement = document.createElement('div');
        loadingElement.className = 'message assistant';
        loadingElement.id = 'loadingMessage';
        
        loadingElement.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="message-content">
                <div class="loading-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        
        messagesContainer.appendChild(loadingElement);
        this.scrollToBottom();
    },
    
    /**
     * 隐藏加载状态
     */
    hideLoading() {
        const loadingElement = document.getElementById('loadingMessage');
        if (loadingElement) {
            loadingElement.remove();
        }
    },
    
    /**
     * 隐藏欢迎消息
     */
    hideWelcome() {
        const welcomeMessage = document.querySelector('.welcome-message');
        if (welcomeMessage) {
            welcomeMessage.style.display = 'none';
        }
    },
    
    /**
     * 滚动到底部
     */
    scrollToBottom() {
        const messagesContainer = document.getElementById('chatMessages');
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    },
    
    /**
     * 渲染Markdown
     */
    renderMarkdown(text) {
        // 配置marked
        marked.setOptions({
            highlight: function(code, lang) {
                if (lang && hljs.getLanguage(lang)) {
                    return hljs.highlight(code, { language: lang }).value;
                }
                return hljs.highlightAuto(code).value;
            },
            breaks: true,
            gfm: true,
        });
        
        return marked.parse(text);
    },
    
    /**
     * 根据错误信息返回友好的错误提示和解决方案
     */
    getErrorMessage(errorMsg) {
        const msg = (errorMsg || '').toLowerCase();
        
        if (msg.includes('401') || msg.includes('authentication') || msg.includes('invalid')) {
            return '**API认证失败**\n\n' +
                '可能原因：API Key无效或已过期\n\n' +
                '解决方案：\n' +
                '1. 点击左侧 **设置** 进入API配置页面\n' +
                '2. 输入正确的API Key\n' +
                '3. 点击 **测试连接** 验证\n' +
                '4. 点击 **保存到.env** 持久化配置';
        }
        
        if (msg.includes('429') || msg.includes('rate limit') || msg.includes('too many')) {
            return '**请求频率超限**\n\n' +
                'API调用过于频繁，请稍后再试。\n\n' +
                '解决方案：\n' +
                '1. 等待30秒后重试\n' +
                '2. 考虑升级API套餐以提高配额';
        }
        
        if (msg.includes('timeout') || msg.includes('timed out')) {
            return '**请求超时**\n\n' +
                '服务器响应超时。\n\n' +
                '解决方案：\n' +
                '1. 检查网络连接是否正常\n' +
                '2. 尝试简化问题（减少工具调用）\n' +
                '3. 稍后重试';
        }
        
        if (msg.includes('network') || msg.includes('fetch') || msg.includes('connection')) {
            return '**网络连接失败**\n\n' +
                '无法连接到后端服务。\n\n' +
                '解决方案：\n' +
                '1. 确认后端服务已启动（python run.py）\n' +
                '2. 检查 http://localhost:8000 是否可访问\n' +
                '3. 检查防火墙是否阻止了连接';
        }
        
        if (msg.includes('500') || msg.includes('internal server')) {
            return '**服务器内部错误**\n\n' +
                '后端处理请求时发生异常。\n\n' +
                '解决方案：\n' +
                '1. 查看终端日志获取详细错误信息\n' +
                '2. 尝试重启服务\n' +
                '3. 检查API配置是否正确';
        }
        
        return '**处理消息时发生错误**\n\n' +
            '错误信息: ' + (errorMsg || '未知错误') + '\n\n' +
            '如问题持续，请检查API配置或重启服务。';
    },
    
    /**
     * 转义HTML
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    
    /**
     * 显示欢迎消息
     */
    showWelcome() {
        const messagesContainer = document.getElementById('chatMessages');
        
        const welcomeHtml = `
            <div class="welcome-message">
                <div class="welcome-icon">
                    <i class="fas fa-robot"></i>
                </div>
                <h3>欢迎使用智能运维Agent</h3>
                <p>我可以帮助您监控和管理 Linux 操作系统，包括：</p>
                <ul>
                    <li><i class="fas fa-server"></i> 查看系统状态（CPU、内存、磁盘）</li>
                    <li><i class="fas fa-network-wired"></i> 网络诊断和连接检查</li>
                    <li><i class="fas fa-cogs"></i> 进程和服务管理</li>
                    <li><i class="fas fa-file-alt"></i> 系统日志分析</li>
                </ul>
                <div class="example-queries">
                    <p>试试问我：</p>
                    <button class="example-btn" data-query="帮我查看一下当前系统的CPU和内存使用情况">查看系统状态</button>
                    <button class="example-btn" data-query="检查一下磁盘空间使用情况">检查磁盘空间</button>
                    <button class="example-btn" data-query="列出当前运行的进程，按CPU使用率排序">查看进程列表</button>
                    <button class="example-btn" data-query="查看系统最近的错误日志">查看错误日志</button>
                </div>
            </div>
        `;
        
        messagesContainer.innerHTML = welcomeHtml;
        
        // 重新绑定示例按钮事件
        document.querySelectorAll('.example-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const query = btn.dataset.query;
                if (query) {
                    document.getElementById('chatInput').value = query;
                    this.sendMessage();
                }
            });
        });
    },
    
    /**
     * 加载对话列表
     */
    async loadConversations() {
        try {
            const result = await API.get('/api/chat/conversations');
            if (result.success) {
                this.conversations = result.data;
                this.renderConversationList();
                
                // 如果有对话，选中第一个；否则创建新对话
                if (this.conversations.length > 0) {
                    this.switchConversation(this.conversations[0].id);
                } else {
                    this.createConversation();
                }
            }
        } catch (error) {
            console.error('加载对话列表失败:', error);
            // 降级：创建本地对话
            this.createConversation();
        }
    },
    
    /**
     * 渲染对话列表
     */
    renderConversationList() {
        const listEl = document.getElementById('conversationList');
        if (!listEl) return;
        
        listEl.innerHTML = this.conversations.map(conv => `
            <div class="conversation-item ${conv.id === this.sessionId ? 'active' : ''}" 
                 data-id="${conv.id}">
                <i class="fas fa-comment"></i>
                <span class="conv-title">${this.escapeHtml(conv.title)}</span>
                <button class="conv-delete" data-id="${conv.id}" title="删除对话">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `).join('');
        
        // 绑定点击事件
        listEl.querySelectorAll('.conversation-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.closest('.conv-delete')) return;
                this.switchConversation(item.dataset.id);
            });
        });
        
        // 绑定删除事件
        listEl.querySelectorAll('.conv-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteConversation(btn.dataset.id);
            });
        });
    },
    
    /**
     * 创建新对话
     */
    async createConversation() {
        try {
            const result = await API.post('/api/chat/conversations', { title: '新对话' });
            if (result.success) {
                const conv = result.data;
                this.conversations.unshift(conv);
                this.renderConversationList();
                this.switchConversation(conv.id);
            }
        } catch (error) {
            console.error('创建对话失败:', error);
            // 降级：本地生成ID
            const localId = 'local_' + Date.now();
            this.sessionId = localId;
            this.showWelcome();
        }
    },
    
    /**
     * 切换对话
     */
    async switchConversation(conversationId) {
        this.sessionId = conversationId;
        
        // 更新UI高亮
        document.querySelectorAll('.conversation-item').forEach(item => {
            item.classList.toggle('active', item.dataset.id === conversationId);
        });
        
        // 更新标题
        const conv = this.conversations.find(c => c.id === conversationId);
        const titleEl = document.getElementById('currentChatTitle');
        if (titleEl && conv) {
            titleEl.textContent = conv.title;
        }
        
        // 加载对话消息
        try {
            const result = await API.get(`/api/chat/conversations/${conversationId}/messages`);
            if (result.success && result.data.length > 0) {
                this.renderMessages(result.data);
            } else {
                this.showWelcome();
            }
        } catch (error) {
            console.error('加载对话消息失败:', error);
            this.showWelcome();
        }
    },
    
    /**
     * 渲染消息列表
     */
    renderMessages(messages) {
        const messagesContainer = document.getElementById('chatMessages');
        messagesContainer.innerHTML = '';
        
        messages.forEach(msg => {
            if (msg.role === 'user') {
                this.addMessage('user', msg.content);
            } else if (msg.role === 'assistant') {
                this.addMessage('assistant', msg.content);
            }
        });
    },
    
    /**
     * 删除对话
     */
    async deleteConversation(conversationId) {
        try {
            await API.delete(`/api/chat/conversations/${conversationId}`);
            
            this.conversations = this.conversations.filter(c => c.id !== conversationId);
            this.renderConversationList();
            
            // 如果删除的是当前对话，切换到第一个对话或创建新对话
            if (conversationId === this.sessionId) {
                if (this.conversations.length > 0) {
                    this.switchConversation(this.conversations[0].id);
                } else {
                    this.createConversation();
                }
            }
            
            App.showNotification('对话已删除', 'success');
        } catch (error) {
            console.error('删除对话失败:', error);
            App.showNotification('删除对话失败', 'error');
        }
    },
    
    /**
     * 清空当前对话
     */
    async clearConversation() {
        if (!this.sessionId) return;
        
        try {
            await API.delete(`/api/chat/conversation/${this.sessionId}`);
            
            const messagesContainer = document.getElementById('chatMessages');
            messagesContainer.innerHTML = '';
            this.showWelcome();
            
            App.showNotification('对话已清空', 'success');
        } catch (error) {
            console.error('清空对话失败:', error);
        }
    },
};

// 导出Chat对象
window.Chat = Chat;
