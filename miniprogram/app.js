// app.js —— 小银杏小程序全局配置
App({
  globalData: {
    // 后端服务地址：本地开发用 http://127.0.0.1:8000
    // 上线前改为已备案的 HTTPS 域名，并在小程序后台配置合法域名
    baseUrl: 'http://127.0.0.1:8000',
    model: 'glm-4.7-flash'
  },
  onLaunch() {}
});
