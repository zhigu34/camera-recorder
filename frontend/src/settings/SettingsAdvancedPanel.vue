<template>
  <section class="settings-section-page">
    <header class="settings-section-header"><span class="settings-section-kicker">ADVANCED</span><h2>高级</h2><p>低频、部署级和敏感配置的边界说明。</p></header>
    <div class="settings-group">
      <div class="settings-group-title"><strong>部署级配置</strong><span>这里不会复制或暴露部署密钥。</span></div>
      <div class="settings-information-block"><strong>部署参数和密钥仍由 .env / Docker 部署配置管理</strong><p>数据库连接、部署端口、服务密钥和其他敏感参数不写入 SQLite 运行时设置，也不会在此页面以明文展示。</p></div>
    </div>
  </section>
</template>
