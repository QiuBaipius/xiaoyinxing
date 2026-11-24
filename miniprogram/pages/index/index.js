// pages/index/index.js —— 小银杏对话页（支持图片、文件输入与文件下载）
const app = getApp();

const CAT_CN = {
  policy: '政策制度', notice: '通知公告', news: '新闻动态', course: '课程选课',
  exam: '考试安排', process: '办事流程', guide: '办事指南', calendar: '校历时间',
  scholarship: '奖助贷', graduation: '毕业学位', service: '校园服务', general: '其他'
};

Page({
  data: {
    messages: [],
    input: '',
    sending: false,
    showWelcome: true,
    images: [],   // data URL 数组
    files: [],    // {name, data(base64), mime}
    suggestions: [
      '如何办理成绩证明？',
      '补考和缓考怎么申请？',
      '奖学金怎么申请？',
      '图书馆研讨间如何预约？',
      '将校历发给我'
    ],
    scrollIntoView: ''
  },

  onLoad() {
    this.history = [];
  },

  onInput(e) {
    this.setData({ input: e.detail.value });
  },

  tapSuggestion(e) {
    this.setData({ input: e.currentTarget.dataset.q });
    this.send();
  },

  // ---------- 图片输入 ----------
  chooseImage() {
    wx.chooseMedia({
      count: 9,
      mediaType: ['image'],
      success: (res) => {
        const fs = wx.getFileSystemManager();
        const imgs = this.data.images.slice();
        res.tempFiles.forEach((f) => {
          try {
            const b64 = fs.readFileSync(f.tempFilePath, 'base64');
            imgs.push('data:image/jpeg;base64,' + b64);
          } catch (e) { /* ignore */ }
        });
        this.setData({ images: imgs });
      }
    });
  },

  // ---------- 文件输入 ----------
  chooseFile() {
    wx.chooseMessageFile({
      count: 3,
      type: 'file',
      success: (res) => {
        const fs = wx.getFileSystemManager();
        const files = this.data.files.slice();
        res.tempFiles.forEach((f) => {
          try {
            const b64 = fs.readFileSync(f.path, 'base64');
            files.push({ name: f.name, data: b64, mime: f.type || '' });
          } catch (e) { /* ignore */ }
        });
        this.setData({ files });
      }
    });
  },

  removeImage(e) {
    const i = e.currentTarget.dataset.i;
    const imgs = this.data.images.slice();
    imgs.splice(i, 1);
    this.setData({ images: imgs });
  },

  removeFile(e) {
    const i = e.currentTarget.dataset.i;
    const files = this.data.files.slice();
    files.splice(i, 1);
    this.setData({ files });
  },

  // ---------- 文件下载 ----------
  downloadFile(e) {
    const url = e.currentTarget.dataset.url;
    const name = e.currentTarget.dataset.name || '';
    wx.downloadFile({
      url,
      success(res) {
        if (res.statusCode === 200) {
          wx.openDocument({
            filePath: res.tempFilePath,
            showMenu: true,
            fail: () => wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '链接已复制' }) })
          });
        } else {
          wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '链接已复制' }) });
        }
      },
      fail: () => wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '链接已复制' }) })
    });
  },

  async send() {
    const text = this.data.input.trim();
    const imgs = this.data.images || [];
    const files = this.data.files || [];
    if ((!text && !imgs.length && !files.length) || this.data.sending) return;

    const msg = text || (imgs.length ? '请查看这张图片' : '请查看我发送的文件');
    const msgs = this.data.messages.concat([{ role: 'user', content: msg, images: imgs, files: files }]);
    this.setData({
      messages: msgs,
      input: '',
      sending: true,
      showWelcome: false,
      images: [],
      files: []
    });
    this.history.push({ role: 'user', content: msg });
    this.scrollToBottom();

    try {
      const res = await this.request('/api/chat', {
        message: msg,
        history: this.history.slice(0, -1),
        stream: false,
        images: imgs,
        files: files.map(f => ({ name: f.name, data: f.data, mime: f.mime }))
      });
      const answer = res.answer || '';
      const sources = res.sources || [];
      const dlFiles = res.files || [];
      const category = res.category || '';
      this.history.push({ role: 'assistant', content: answer });

      this.setData({
        messages: this.data.messages.concat([{
          role: 'assistant', content: answer, category: CAT_CN[category] || '',
          sources, files: dlFiles
        }]),
        sending: false
      });
    } catch (e) {
      this.setData({
        messages: this.data.messages.concat([{
          role: 'assistant', content: '抱歉，请求出错了：' + (e.message || e.errMsg || '网络错误'),
          category: '', sources: [], files: []
        }]),
        sending: false
      });
    }
    this.scrollToBottom();
  },

  request(path, data) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: app.globalData.baseUrl + path,
        method: 'POST',
        data,
        header: { 'Content-Type': 'application/json' },
        success(res) {
          if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data);
          else reject(new Error('HTTP ' + res.statusCode));
        },
        fail(err) { reject(err); }
      });
    });
  },

  scrollToBottom() {
    this.setData({ scrollIntoView: 'msg-' + (this.data.messages.length - 1) });
  }
});
