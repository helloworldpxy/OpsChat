/**
 * 对话功能模块
 * 处理聊天界面的所有交互
 */

const Chat = {
    sessionId: null,
    isProcessing: false,
    conversations: [],
    _streamSeq: 0,
    _abortController: null,
    _convRequestSeq: 0,
    _convListSeq: 0,
    
    /**
     * 初始化对话模块
     */
    init() {
        this.bindEvents();
        this.initSearch();
        this.loadConversations();
        this.initResponsive();
    },
    
    /**
     * 窄屏自动折叠：<1100px 折叠详情列，<800px 折叠会话栏
     */
    initResponsive() {
        // 恢复详情列折叠状态（默认展开）
        const detailSaved = localStorage.getItem('detailCollapsed') === '1';
        if (detailSaved) {
            const panel = document.getElementById('detailPanel');
            if (panel) panel.classList.add('collapsed');
            document.body.classList.remove('detail-open');
        }
        const apply = () => {
            const w = window.innerWidth;
            if (w < 1100) this.closeDetailPanel();
            if (w < 800) {
                document.getElementById('conversationSidebar')?.classList.add('collapsed');
            }
        };
        apply();
        window.addEventListener('resize', () => apply());
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
            chatInput.addEventListener('compositionstart', () => {
                chatInput.dataset.composing = 'true';
            });
            chatInput.addEventListener('compositionend', () => {
                delete chatInput.dataset.composing;
            });
            chatInput.addEventListener('keydown', (e) => {
                // Escape：折叠所有展开的工具卡/审批卡
                if (e.key === 'Escape') {
                    document.querySelectorAll('.tool-card.expanded').forEach(el => {
                        el.querySelector('.tool-card-toggle')?.click();
                    });
                    return;
                }
                // Ctrl / Cmd + Enter：强制发送（IME 组合输入中也发送）
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    this.sendMessage();
                    return;
                }
                // Enter 发送：IME 组合输入（确认候选词）时不触发
                if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !chatInput.dataset.composing) {
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
        
        // 对话列表侧边栏切换（持久化）
        const convSidebarToggle = document.getElementById('convSidebarToggle');
        if (convSidebarToggle) {
            const savedConv = localStorage.getItem('convSidebarCollapsed') === '1';
            if (savedConv) document.getElementById('conversationSidebar')?.classList.add('collapsed');
            convSidebarToggle.addEventListener('click', () => {
                const el = document.getElementById('conversationSidebar');
                el.classList.toggle('collapsed');
                localStorage.setItem('convSidebarCollapsed', el.classList.contains('collapsed') ? '1' : '0');
            });
        }
        
        // 详情列开关
        const detailPanelToggle = document.getElementById('detailPanelToggle');
        if (detailPanelToggle) {
            detailPanelToggle.addEventListener('click', () => this.toggleDetailPanel());
        }
        const detailPanelClose = document.getElementById('detailPanelClose');
        if (detailPanelClose) {
            detailPanelClose.addEventListener('click', () => this.closeDetailPanel());
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
        this.resetFooterMetrics();
        this.startElapsedTimer();

        const seq = ++this._streamSeq;
        this._abortController = new AbortController();
        
        try {
            // 流式发送消息
            let preToolContent = '';   // 工具调用前的AI文字（如"好的，我来查看..."）
            let postToolContent = '';  // 工具调用后的AI总结
            let messageElement = null;
            let sawTools = false;
            const cardMap = new Map(); // 工具调用ID -> 工具卡片元素

            // 重置审批相关状态
            this.approvalCard = null;
            this.approvalMessageEl = null;
            this.approvalContent = '';

            await API.sendMessageStream(
                message,
                this.sessionId,
                // onChunk
                (chunk) => {
                    if (seq !== this._streamSeq) return; // 旧流残留分片丢弃，避免污染新会话
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
                        this.showToolCalls(chunk.tool_calls, cardMap);
                    } else if (chunk.type === 'tool_result') {
                        this.showToolResult(chunk.tool_name, chunk.result, chunk.tool_call_id, cardMap);
                    } else if (chunk.type === 'permission_asked') {
                        // 高危操作审批卡
                        sawTools = true;
                        if (preToolContent && !messageElement) {
                            messageElement = this.addMessage('assistant', preToolContent.trim());
                        }
                        this.renderApprovalCard(chunk.request, chunk.message || '');
                    } else if (chunk.type === 'context_usage') {
                        // ContextMeter：上下文占用环更新
                        this.updateContextMeter(chunk);
                    } else if (chunk.type === 'finish') {
                        // 消息元信息行 + 页脚指标
                        this.setLastMeta(chunk.model, chunk.elapsed_ms);
                        this.updateFooterMetrics(chunk);
                    } else if (chunk.type === 'title') {
                        // 自动生成的会话标题
                        this.applyNewTitle(chunk.title);
                    } else if (chunk.type === 'error') {
                        if (!messageElement) {
                            messageElement = this.addMessage('assistant', '');
                        }
                        this.updateMessage(messageElement, this.getErrorMessage(chunk.message));
                    }
                },
                // onDone
                () => {
                    if (seq !== this._streamSeq) return;
                    this.hideLoading();
                    this.isProcessing = false;
                    this.stopElapsedTimer();
                },
                // onError
                (error) => {
                    if (seq !== this._streamSeq) return;
                    console.error('流式请求失败:', error);
                    this.hideLoading();
                    this.isProcessing = false;
                    this.stopElapsedTimer();
                    this.addMessage('assistant', this.getErrorMessage(error.message || '网络连接失败'));
                },
                { signal: this._abortController.signal }
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
        avatar.textContent = role === 'user' ? '我' : 'AI';
        
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
     * 显示工具调用（工具卡片，IN 侧）
     */
    showToolCalls(toolCalls, cardMap = new Map()) {
        const messagesContainer = document.getElementById('chatMessages');
        
        toolCalls.forEach(toolCall => {
            const card = ToolCards.renderToolCall(toolCall);
            if (toolCall.id) cardMap.set(toolCall.id, card);
            // 点击卡片头部 → 详情列全高审视 IN/OUT
            card.addEventListener('click', (e) => {
                if (e.target.closest('.tool-card-toggle') || e.target.closest('button')) return;
                this.openToolDetail(card);
            });
            messagesContainer.appendChild(card);
        });
        
        this.scrollToBottom();
    },
    
    /**
     * 显示/更新工具结果（OUT 侧，按 call_id 关联前置卡片）
     */
    showToolResult(toolName, result, callId, cardMap = new Map()) {
        const messagesContainer = document.getElementById('chatMessages');
        
        const rendered = ToolCards.renderToolResult(toolName, result, callId, cardMap);
        if (rendered.created) {
            messagesContainer.appendChild(rendered.card);
        }
        
        this.scrollToBottom();
    },
    
    /**
     * 风险等级中文标签
     */
    riskLabel(risk) {
        const map = { low: '低风险', medium: '中风险', high: '高风险', critical: '严重' };
        return map[risk] || '高危操作';
    },

    /**
     * 渲染高危操作审批卡
     */
    renderApprovalCard(request, message) {
        const messagesContainer = document.getElementById('chatMessages');

        const risk = (request.metadata && request.metadata.risk_level) || 'high';
        const args = ToolCards.summarize(request.tool_name, request.tool_params || {});
        const glyph = ToolCards.meta(request.tool_name).glyph;

        const card = document.createElement('div');
        card.className = 'approval-card';

        const header = document.createElement('div');
        header.className = 'approval-header';
        header.innerHTML = `
            <span class="approval-icon">审</span>
            <span class="approval-title">需要授权</span>
            <span class="risk-badge risk-${ToolCards.escapeHtml(risk)}">${this.riskLabel(risk)}</span>
        `;

        const toolRow = document.createElement('div');
        toolRow.className = 'approval-tool-row';
        toolRow.innerHTML = `
            <span class="tool-card-icon">${ToolCards.escapeHtml(glyph)}</span>
            <span class="tool-name">${ToolCards.escapeHtml(request.tool_name)}</span>
            <code class="approval-args">${ToolCards.escapeHtml(args)}</code>
        `;

        const msg = document.createElement('div');
        msg.className = 'approval-msg';
        msg.textContent = message || '该操作需要您确认后执行';

        const pwWrap = document.createElement('div');
        pwWrap.className = 'approval-password';
        pwWrap.innerHTML = '<input type="password" placeholder="sudo 密码（Linux 提权需要，仅本次使用）" autocomplete="off">';

        const actions = document.createElement('div');
        actions.className = 'approval-actions';
        const btnReject = document.createElement('button');
        btnReject.className = 'btn btn-danger';
        btnReject.type = 'button';
        btnReject.textContent = '拒绝';
        btnReject.dataset.reply = 'reject';
        const btnOnce = document.createElement('button');
        btnOnce.className = 'btn btn-secondary';
        btnOnce.type = 'button';
        btnOnce.textContent = '仅此一次';
        btnOnce.dataset.reply = 'once';
        const btnAlways = document.createElement('button');
        btnAlways.className = 'btn btn-primary';
        btnAlways.type = 'button';
        btnAlways.textContent = '始终允许';
        btnAlways.dataset.reply = 'always';
        actions.append(btnReject, btnOnce, btnAlways);

        const statusEl = document.createElement('div');
        statusEl.className = 'approval-status hidden';

        const detailEl = document.createElement('div');
        detailEl.className = 'approval-detail';

        card.append(header, toolRow, msg, pwWrap, actions, statusEl, detailEl);

        // 三态按钮
        actions.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                const pw = pwWrap.querySelector('input')?.value || '';
                this.handleApproval(card, request, btn.dataset.reply, pw);
            });
        });

        messagesContainer.appendChild(card);
        this.approvalCard = card;
        this.scrollToBottom();
        return card;
    },

    /**
     * 处理审批回复（once/always/reject）
     * 期间按钮禁用，防止重复提交
     */
    async handleApproval(card, request, reply, password) {
        const buttons = card.querySelectorAll('.approval-actions button');
        const statusEl = card.querySelector('.approval-status');
        const pwWrap = card.querySelector('.approval-password');

        buttons.forEach(b => { b.disabled = true; });
        statusEl.classList.remove('hidden');
        statusEl.textContent = '';
        card.classList.add('processing');

        try {
            // 拒绝：非流式，无需密码
            if (reply === 'reject') {
                const res = await API.confirmToolExecution({
                    session_id: this.sessionId,
                    request_id: request.request_id,
                    reply: 'reject',
                    stream: false,
                });
                card.classList.remove('processing');
                card.classList.add('rejected');
                statusEl.textContent = res?.message || '已拒绝该操作';
                return;
            }

            // once / always：流式执行，等待结果；期间占用 isProcessing 防并发发送
            const seq = ++this._streamSeq;
            this._abortController = new AbortController();
            this.isProcessing = true;
            card.classList.add('approved');
            if (pwWrap) {
                pwWrap.style.display = 'none';
                const pwInput = pwWrap.querySelector('input');
                if (pwInput) pwInput.value = '';
            }
            statusEl.textContent = reply === 'always'
                ? '已批准并设为「始终允许」，正在执行...'
                : '已批准，正在执行...';

            await API.confirmPermissionStream(
                { sessionId: this.sessionId, requestId: request.request_id, reply, password },
                (chunk) => {
                    if (seq !== this._streamSeq) return; // 旧审批流残留分片丢弃
                    if (chunk.type === 'content') {
                        this.appendAssistantContent(chunk.content);
                    } else if (chunk.type === 'tool_result') {
                        card.classList.add('executed');
                        const ok = chunk.result && chunk.result.success !== false;
                        statusEl.textContent = ok ? '执行完成' : '执行失败';
                        // 追加 OUT 详情行
                        const outRow = document.createElement('div');
                        outRow.className = 'tool-card-row';
                        outRow.innerHTML = `<span class="tool-card-label">OUT</span><pre><code>${ToolCards.escapeHtml(JSON.stringify(chunk.result, null, 2))}</code></pre>`;
                        card.querySelector('.approval-detail')?.appendChild(outRow);
                    } else if (chunk.type === 'finish') {
                        this.setLastMeta(chunk.model, chunk.elapsed_ms);
                        this.updateFooterMetrics(chunk);
                    } else if (chunk.type === 'error') {
                        statusEl.textContent = chunk.message || '执行出错';
                    }
                },
                () => {
                    if (seq !== this._streamSeq) return;
                    buttons.forEach(b => { b.disabled = false; });
                    card.classList.remove('processing');
                    card.classList.add('done');
                    if (!card.classList.contains('executed') && !card.classList.contains('rejected')) {
                        statusEl.textContent = '已完成';
                    }
                    this.isProcessing = false;
                },
                (error) => {
                    if (seq !== this._streamSeq) return;
                    statusEl.textContent = '执行失败: ' + (error.message || '未知错误');
                    buttons.forEach(b => { b.disabled = false; });
                    card.classList.remove('processing', 'approved');
                    if (pwWrap) pwWrap.style.display = '';
                    this.isProcessing = false;
                },
                { signal: this._abortController.signal }
            );
        } catch (error) {
            statusEl.textContent = '提交失败: ' + (error.message || '未知错误');
            buttons.forEach(b => { b.disabled = false; });
            card.classList.remove('processing', 'approved');
            this.isProcessing = false;
        }
    },

    /**
     * 追加审批确认后的总结内容到助手消息
     */
    appendAssistantContent(text) {
        if (!text) return;
        if (!this.approvalMessageEl) {
            this.approvalMessageEl = this.addMessage('assistant', '');
        }
        this.approvalContent += text;
        this.updateMessage(this.approvalMessageEl, this.approvalContent);
    },

    /**
     * 为最后一条助手消息追加元信息行（模型 · 耗时）
     */
    setLastMeta(model, elapsedMs) {
        const messagesContainer = document.getElementById('chatMessages');
        const last = messagesContainer.querySelector('.message.assistant:last-of-type');
        if (!last || !elapsedMs) return;

        const existing = last.querySelector('.message-meta');
        if (existing) existing.remove();

        const meta = document.createElement('div');
        meta.className = 'message-meta';
        const secs = (elapsedMs / 1000).toFixed(1);
        meta.textContent = `${model || '模型'} · ${secs}s`;
        last.appendChild(meta);
    },

    /* ==================== 详情列（阶段三） ==================== */

    /**
     * 打开工具详情列，全高展示指定工具卡的 IN / OUT
     */
    openToolDetail(card) {
        const panel = document.getElementById('detailPanel');
        const body = document.getElementById('detailPanelBody');
        const titleEl = document.getElementById('detailPanelTitle');
        if (!panel || !body) return;

        const toolName = card.dataset.tool || '工具详情';
        const meta = ToolCards.meta(toolName);
        const argsEl = card.querySelector('.tool-card-args');
        titleEl.textContent = meta.title || toolName;

        // 克隆卡片 body（IN/OUT 行）到详情列，强制展开全高查看
        const srcBody = card.querySelector('.tool-card-body');
        const cloneBody = srcBody ? srcBody.cloneNode(true) : document.createElement('div');
        cloneBody.classList.remove('hidden');
        body.innerHTML = '';
        body.appendChild(cloneBody);

        // 状态角标
        const statusEl = document.createElement('div');
        statusEl.className = 'detail-panel-status';
        statusEl.innerHTML = argsEl && argsEl.textContent
            ? `<span class="detail-summary">${ToolCards.escapeHtml(argsEl.textContent)}</span>`
            : '';
        body.insertBefore(statusEl, body.firstChild);

        panel.classList.remove('collapsed');
        document.body.classList.add('detail-open');
        this._lastOpenedCard = card;
    },

    /**
     * 切换详情列开关
     */
    toggleDetailPanel() {
        const panel = document.getElementById('detailPanel');
        if (!panel) return;
        if (panel.classList.contains('collapsed')) {
            // 有选中卡片则展示，否则仅展开
            if (this._lastOpenedCard && document.contains(this._lastOpenedCard)) {
                this.openToolDetail(this._lastOpenedCard);
            } else {
                panel.classList.remove('collapsed');
                document.body.classList.add('detail-open');
            }
        } else {
            this.closeDetailPanel();
        }
        localStorage.setItem('detailCollapsed', panel.classList.contains('collapsed') ? '1' : '0');
    },

    /**
     * 关闭详情列
     */
    closeDetailPanel() {
        const panel = document.getElementById('detailPanel');
        if (panel) panel.classList.add('collapsed');
        document.body.classList.remove('detail-open');
        // 与 toggleDetailPanel 一致地持久化状态，避免手动关闭后刷新又展开
        localStorage.setItem('detailCollapsed', '1');
    },

    /* ==================== ContextMeter 与页脚指标（阶段三） ==================== */

    /**
     * 更新上下文占用环（SVG 分段：system / tools / messages）
     */
    updateContextMeter(usage) {
        if (!usage) return;
        const meter = document.getElementById('contextMeter');
        const label = document.getElementById('meterLabel');
        if (!meter) return;

        const limit = usage.limit || 0;
        const total = usage.total || 0;
        const pct = limit ? Math.min((total / limit) * 100, 100) : 0;
        const C = 100; // 圆环周长 ≈ 2π×15.9155 ≈ 100

        // 分段累计偏移
        let acc = 0;
        ['system', 'tools', 'messages'].forEach(key => {
            const segPct = limit ? Math.min((usage[key] || 0) / limit * 100, 100) : 0;
            const el = meter.querySelector(`.meter-${key}`);
            if (el) {
                el.style.strokeDasharray = `${segPct} ${Math.max(C - segPct, 0)}`;
                el.style.strokeDashoffset = `${-acc}`;
            }
            acc += segPct;
        });

        // 总量背景环
        const bg = meter.querySelector('.meter-bg');
        if (bg) {
            bg.style.strokeDasharray = `${pct} ${C - pct}`;
            bg.style.strokeDashoffset = '0';
        }

        meter.classList.toggle('meter-warn', pct > 60);
        meter.classList.toggle('meter-danger', pct > 85);
        label.textContent = `${Math.round(pct)}%`;
        meter.title = `上下文占用 ${Math.round(pct)}%\n` +
            `system ${usage.system || 0} · tools ${usage.tools || 0} · messages ${usage.messages || 0}\n` +
            `合计 ${total} / ${limit}`;
    },

    /**
     * 重置页脚指标（新一轮开始时 / 切换会话时）
     */
    resetFooterMetrics() {
        const elapsed = document.getElementById('fmElapsed');
        if (elapsed) elapsed.textContent = '0.0s';
        const ttft = document.getElementById('fmTtft');
        if (ttft) ttft.textContent = '--';
        const speed = document.getElementById('fmSpeed');
        if (speed) speed.textContent = '--';
        const tokens = document.getElementById('fmTokens');
        if (tokens) tokens.textContent = '--';
        // 重置上下文占用环
        const meter = document.getElementById('contextMeter');
        if (meter) {
            const bg = meter.querySelector('.meter-bg');
            if (bg) {
                bg.style.strokeDasharray = '0 100';
                bg.style.strokeDashoffset = '0';
            }
            meter.classList.remove('meter-warn', 'meter-danger');
            const label = document.getElementById('meterLabel');
            if (label) label.textContent = '0%';
            meter.title = '';
        }
    },

    /**
     * 更新页脚指标（TTFT / 速率 / 耗时 / tokens），并停止计时器
     */
    updateFooterMetrics(finish) {
        const ttft = document.getElementById('fmTtft');
        const speed = document.getElementById('fmSpeed');
        const elapsed = document.getElementById('fmElapsed');
        const tokens = document.getElementById('fmTokens');

        if (ttft && finish.ttft_ms != null) ttft.textContent = (finish.ttft_ms / 1000).toFixed(2) + 's';
        if (speed && finish.tokens_per_sec != null) speed.textContent = finish.tokens_per_sec + ' tok/s';
        if (elapsed && finish.elapsed_ms != null) elapsed.textContent = (finish.elapsed_ms / 1000).toFixed(1) + 's';
        if (tokens && finish.usage) tokens.textContent = finish.usage.total_tokens + ' tok';

        this.stopElapsedTimer();
    },

    /**
     * 启动整轮耗时计时（页脚实时刷新）
     */
    startElapsedTimer() {
        this.elapsedStart = Date.now();
        this.stopElapsedTimer();
        this.elapsedTimer = setInterval(() => {
            const el = document.getElementById('fmElapsed');
            if (el) el.textContent = ((Date.now() - this.elapsedStart) / 1000).toFixed(1) + 's';
        }, 250);
    },

    /**
     * 停止耗时计时器
     */
    stopElapsedTimer() {
        if (this.elapsedTimer) {
            clearInterval(this.elapsedTimer);
            this.elapsedTimer = null;
        }
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
            <div class="message-avatar">AI</div>
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
        
        // 安全净化：防止 LLM 输出中的 HTML/脚本注入（XSS）
        const raw = marked.parse(text);
        if (window.DOMPurify) {
            return DOMPurify.sanitize(raw);
        }
        // DOMPurify 未加载时降级为纯文本转义
        return this.escapeHtml(raw).replace(/\n/g, '<br>');
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
                <div class="welcome-icon">AI</div>
                <h3>欢迎使用智能运维Agent</h3>
                <p>我可以帮助您监控和管理 Linux 操作系统，包括：</p>
                <ul>
                    <li>查看系统状态（CPU、内存、磁盘）</li>
                    <li>网络诊断和连接检查</li>
                    <li>进程和服务管理</li>
                    <li>系统日志分析</li>
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
     * 应用自动生成的会话标题（流式 title 事件）
     */
    applyNewTitle(title) {
        if (!title) return;
        const titleEl = document.getElementById('currentChatTitle');
        if (titleEl) titleEl.textContent = title;
        const conv = this.conversations.find(c => c.id === this.sessionId);
        if (conv) conv.title = title;
        this.renderConversationList();
    },

    /**
     * 加载对话列表
     */
    async loadConversations() {
        const reqSeq = ++this._convListSeq;
        try {
            const result = await API.get('/api/chat/conversations');
            // F3: 期间用户新建了会话则丢弃本次过期列表，避免覆盖新会话
            if (reqSeq !== this._convListSeq) return;
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
            if (reqSeq !== this._convListSeq) return;
            console.error('加载对话列表失败:', error);
            // 降级：创建本地对话
            this.createConversation();
        }
    },

    /**
     * 按日期分组（今天 / 昨天 / 7天内 / 更早）
     */
    groupByDate(convs) {
        const groups = { today: [], yesterday: [], week: [], earlier: [] };
        const todayStart = new Date();
        todayStart.setHours(0, 0, 0, 0);
        const yesterdayStart = new Date(todayStart);
        yesterdayStart.setDate(todayStart.getDate() - 1);
        const weekStart = new Date(todayStart);
        weekStart.setDate(todayStart.getDate() - 7);

        convs.forEach(conv => {
            const d = conv.updated_at ? new Date(conv.updated_at) : null;
            const day = d ? new Date(d.getFullYear(), d.getMonth(), d.getDate()) : todayStart;
            if (!d || day >= todayStart) groups.today.push(conv);
            else if (day >= yesterdayStart) groups.yesterday.push(conv);
            else if (day >= weekStart) groups.week.push(conv);
            else groups.earlier.push(conv);
        });

        const labels = { today: '今天', yesterday: '昨天', week: '7天内', earlier: '更早' };
        const out = {};
        ['today', 'yesterday', 'week', 'earlier'].forEach(k => {
            if (groups[k].length) out[labels[k]] = groups[k];
        });
        return out;
    },

    /**
     * 渲染对话列表（按日期分组）
     */
    renderConversationList() {
        const listEl = document.getElementById('conversationList');
        if (!listEl) return;
        if (this._searchMode) return;

        const groups = this.groupByDate(this.conversations);
        listEl.innerHTML = Object.entries(groups).map(([label, convs]) => `
            <div class="conversation-group-label">${label}</div>
            ${convs.map(conv => this.conversationItemHtml(conv)).join('')}
        `).join('');

        this.bindConversationItemEvents(listEl);
    },

    /**
     * 单个会话条目 HTML
     */
    conversationItemHtml(conv) {
        const active = conv.id === this.sessionId ? 'active' : '';
        const tokens = conv.total_tokens || 0;
        const tokenLabel = tokens > 0 ? `<span class="conv-tokens">${this.formatTokens(tokens)} tok</span>` : '';
        return `
            <div class="conversation-item ${active}" data-id="${this.escapeHtml(conv.id)}">
                <span class="conv-glyph">聊</span>
                <span class="conv-title">${this.escapeHtml(conv.title)}</span>
                ${tokenLabel}
                <button class="conv-delete" data-id="${this.escapeHtml(conv.id)}" title="删除对话">
                    <span>×</span>
                </button>
            </div>
        `;
    },

    formatTokens(n) {
        const num = Number(n);
        if (!Number.isFinite(num) || num <= 0) return '0';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
        return String(num);
    },

    /**
     * 绑定会话列表点击 / 删除事件（删除需两次确认）
     */
    bindConversationItemEvents(container) {
        if (!this._deleteTimers) this._deleteTimers = new Map();

        // 绑定点击事件
        container.querySelectorAll('.conversation-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.closest('.conv-delete')) return;
                this.switchConversation(item.dataset.id);
            });
        });

        // 绑定删除事件（两次确认）
        container.querySelectorAll('.conv-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = btn.dataset.id;
                const item = btn.closest('.conversation-item');

                if (this._deleteTimers.has(id)) {
                    // 第二次点击：确认删除
                    clearTimeout(this._deleteTimers.get(id));
                    this._deleteTimers.delete(id);
                    this.deleteConversation(id);
                } else {
                    // 第一次点击：进入确认态（2.5s）
                    btn.innerHTML = '<span>确认</span>';
                    btn.classList.add('confirming');
                    item.classList.add('confirming-delete');
                    const timer = setTimeout(() => {
                        this._deleteTimers.delete(id);
                        btn.innerHTML = '<span>×</span>';
                        btn.classList.remove('confirming');
                        item.classList.remove('confirming-delete');
                    }, 2500);
                    this._deleteTimers.set(id, timer);
                }
            });
        });
    },

    /* ==================== 会话全文检索（阶段四） ==================== */

    /**
     * 初始化会话搜索框（防抖）
     */
    initSearch() {
        const input = document.getElementById('conversationSearch');
        if (!input) return;
        input.addEventListener('input', () => {
            clearTimeout(this._searchTimer);
            const q = input.value;
            this._searchTimer = setTimeout(() => this.conversationSearch(q), 300);
        });
        // 搜索框清空时恢复列表
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                input.value = '';
                this.conversationSearch('');
            }
        });
    },

    /**
     * 会话全文检索（FTS5，命中结果点击切换会话）
     */
    async conversationSearch(q) {
        const listEl = document.getElementById('conversationList');
        const resultsEl = document.getElementById('conversationSearchResults');
        if (!listEl || !resultsEl) return;

        q = (q || '').trim();
        if (!q) {
            this._searchMode = false;
            listEl.style.display = '';
            resultsEl.style.display = 'none';
            this.renderConversationList();
            return;
        }

        this._searchMode = true;
        listEl.style.display = 'none';
        resultsEl.style.display = '';
        resultsEl.innerHTML = '<div class="search-loading">搜索中...</div>';

        try {
            const res = await API.search(q, 'messages', 30);
            const data = res.data || [];
            if (!data.length) {
                resultsEl.innerHTML = '<div class="search-empty">无匹配结果</div>';
                return;
            }

            // 按会话分组展示命中
            const byConv = new Map();
            data.forEach(hit => {
                if (!byConv.has(hit.conversation_id)) byConv.set(hit.conversation_id, []);
                byConv.get(hit.conversation_id).push(hit);
            });

            resultsEl.innerHTML = [...byConv.entries()].map(([cid, hits]) => `
                <div class="search-group">
                    <div class="search-group-header" data-cid="${this.escapeHtml(cid)}">
                        <span class="conv-glyph">聊</span>
                        <span class="conv-title">${this.escapeHtml(hits[0].conversation_title || '对话')}</span>
                        <span class="search-group-count">${hits.length}</span>
                    </div>
                    ${hits.slice(0, 3).map(hit => `
                        <div class="search-hit" data-cid="${this.escapeHtml(cid)}">
                            <span class="search-hit-preview">${this.escapeHtml(hit.content)}</span>
                        </div>
                    `).join('')}
                </div>
            `).join('');

            const switchHandler = async (cid) => {
                await this.switchConversation(cid);
                const input = document.getElementById('conversationSearch');
                if (input) {
                    input.value = '';
                    this.conversationSearch('');
                }
            };
            resultsEl.querySelectorAll('.search-group-header').forEach(el => {
                el.addEventListener('click', () => switchHandler(el.dataset.cid));
            });
            resultsEl.querySelectorAll('.search-hit').forEach(el => {
                el.addEventListener('click', () => switchHandler(el.dataset.cid));
            });
        } catch (error) {
            console.error('会话检索失败:', error);
            resultsEl.innerHTML = '<div class="search-empty">搜索失败，请稍后重试</div>';
        }
    },
    
    /**
     * 创建新对话
     */
    async createConversation() {
        // F3: 使在途的 loadConversations 响应失效，避免覆盖刚创建的会话
        ++this._convListSeq;
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
            // 降级：本地生成ID（复位发送状态，防止卡死）
            if (this._abortController) this._abortController.abort();
            ++this._streamSeq;
            this.isProcessing = false;
            this.hideLoading();
            this.stopElapsedTimer();
            const localId = 'local_' + Date.now();
            this.sessionId = localId;
            this.showWelcome();
        }
    },
    
    /**
     * 切换对话
     */
    async switchConversation(conversationId) {
        // 中止进行中的流式请求，防止旧流追加消息污染新会话
        if (this._abortController) this._abortController.abort();
        ++this._streamSeq;
        this.isProcessing = false;
        this.hideLoading();
        this.stopElapsedTimer();
        this.resetFooterMetrics(); // 切换会话后清空上一会话的指标与上下文环
        // F7: 清空审批卡残留引用，避免复用已脱离 DOM 的节点
        this.approvalCard = null;
        this.approvalMessageEl = null;
        this.approvalContent = '';
        const reqSeq = ++this._convRequestSeq;

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
            if (reqSeq !== this._convRequestSeq) return; // 已有更新的切换，丢弃本次响应
            if (result.success && result.data.length > 0) {
                this.renderMessages(result.data);
            } else {
                this.showWelcome();
            }
        } catch (error) {
            if (reqSeq !== this._convRequestSeq) return;
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

        // 中止进行中的流式请求，防止残留流继续追加消息
        if (this._abortController) this._abortController.abort();
        ++this._streamSeq;
        ++this._convRequestSeq; // 使在途的会话切换响应失效，避免重新填充已清空的聊天区
        this.resetFooterMetrics();
        this.approvalCard = null;
        this.approvalMessageEl = null;
        this.approvalContent = '';
        
        try {
            await API.delete(`/api/chat/conversation/${this.sessionId}`);
            
            const messagesContainer = document.getElementById('chatMessages');
            messagesContainer.innerHTML = '';
            this.showWelcome();
            this.hideLoading();
            this.isProcessing = false;
            
            App.showNotification('对话已清空', 'success');
        } catch (error) {
            console.error('清空对话失败:', error);
            this.isProcessing = false;
            this.hideLoading();
            App.showNotification('清空对话失败', 'error');
        }
    },
};

// 导出Chat对象
window.Chat = Chat;
