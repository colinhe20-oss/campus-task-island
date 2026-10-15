import './publish-choice.css';

export function PublishChoicePage() {
  return <><div className="page-heading"><div><p className="eyebrow">选择要发布的内容</p><h1>发布任务</h1><p className="subheading">先选择种类，再填写对应的内容和安排。</p></div></div>
    <div className="publish-types">
      <a className="panel publish-type" href="#/tasks/new?type=ordinary"><span className="publish-type-icon">▦</span><h2>普通任务</h2><p>寻找同学一起完成具体需求，通过直接接取或申请确认、协作和验收推进。</p><ul><li>学习、创作、音乐、生活互助</li><li>填写需求、完成标准、地点和截止时间</li><li>例如：找同学协助拍摄社团活动照片</li></ul><span className="button">选择普通任务 →</span></a>
      <a className="panel publish-type activity-type" href="#/tasks/new?type=activity"><span className="publish-type-icon">◷</span><h2>综素活动</h2><p>发布供同学报名参加的活动，设置报名窗口、名额与审核方式。</p><ul><li>二课分、美育分、形策二分</li><li>填写活动时间、参与条件与活动方自报的认定说明</li><li>学校正式认定尚未对接</li></ul><span className="button">选择综素活动 →</span></a>
      <a className="panel publish-type volunteer-type" href="#/tasks/new?type=volunteer"><span className="publish-type-icon">♡</span><h2>志愿服务</h2><p>按岗位招募志愿者，记录实际参与，由发布者核验服务小时。</p><ul><li>分岗位时段、名额、审核与候补</li><li>预计小时、实际服务与活动方确认分开展示</li><li>学校正式认定尚未对接</li></ul><span className="button">选择志愿服务 →</span></a>
      <a className="panel publish-type discovery-type" href="#/tasks/new?type=discovery"><span className="publish-type-icon">⌖</span><h2>校园发现</h2><p>图文记录校园情况，由同学评论补充、发布者更新状态。</p><ul><li>公共设施问题、安全与通行提醒</li><li>有趣发现、校园生活分享</li><li>所有登录用户均可发布，保留变化历史</li></ul><span className="button">选择校园发现 →</span></a>
    </div>
  </>;
}
