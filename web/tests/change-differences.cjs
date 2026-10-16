const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const ts=require('typescript');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(
  ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {Diff}=require('../src/changes.tsx');
const live=require('../src/live.tsx');
const {TaskTermsPanel}=require('../src/TaskTerms.tsx');
const render=element=>renderToStaticMarkup(element);
const difference=(before,after)=>({field:'cancellation_settlement_fen',before,after});

for(const [amount,expected] of [[2550,'¥25.50'],[1,'¥0.01'],[0,'¥0.00（无需结算）']]){
  test(`取消结算 ${amount} 分显示金额含义和人民币单位`,()=>{
    const html=render(React.createElement(Diff,{differences:[difference(null,amount)]}));
    assert.ok(html.includes('<strong>取消结算金额</strong>'),html);
    assert.ok(html.includes(`<p style="white-space:pre-wrap">${expected}</p>`),html);
    assert.ok(html.includes('<small>变更前</small><p style="white-space:pre-wrap">无</p>'),html);
    assert.ok(!html.includes('阶段完成要求'),html);
  });
}

test('取消结算的变更前后金额都换算为元，零元明确表示无需结算',()=>{
  const html=render(React.createElement(Diff,{differences:[difference(2550,0)]}));
  assert.ok(html.includes('<small>变更前</small><p style="white-space:pre-wrap">¥25.50</p>'),html);
  assert.ok(html.includes('<small>拟变更为</small><p style="white-space:pre-wrap">¥0.00（无需结算）</p>'),html);
});

test('固定报酬仍按元展示，阶段完成要求中的数字保持原文',()=>{
  const html=render(React.createElement(Diff,{differences:[
    {field:'reward_amount_fen',before:100,after:2550},
    {field:'stages.stage-1.completion_criteria',stage_title:'第一阶段',before:'原要求',after:'2550'},
  ]}));
  assert.ok(html.includes('<strong>固定报酬</strong>')&&html.includes('¥1.00')&&html.includes('¥25.50'),html);
  assert.ok(html.includes('第一阶段 · 阶段完成要求'),html);
  assert.ok(html.includes('<p style="white-space:pre-wrap">2550</p>'),html);
});

const user={id:'owner',username:'owner',display_name:'发布者'};
const task={id:'task-1',publisher_id:'owner',assignee_id:'helper',status:'in_progress',
  reward_type:'paid',reward_amount_fen:5000,terms_version:1,collaboration_version:1,deadline:'2026-10-17T12:00:00+08:00'};
for(const [status,viewer,expectedAction] of [
  ['pending',user,'撤销申请'],
  ['pending',{id:'helper',username:'helper',display_name:'接取者'},'同意并生效'],
  ['approved',user,'已通过'],
]){
  test(`协作面板 ${status}/${viewer.id} 的申请或历史正确显示取消结算金额`,()=>{
    const original=live.useLiveResource;
    live.useLiveResource=url=>({data:url?.endsWith('/changes')?{items:[{
      id:'change-1',kind:'cancel',status,requester_id:user.id,terms_version:1,version:1,
      created_at:'2026-10-16T12:00:00+08:00',reason:'双方协商取消',differences:[difference(null,2550)],
    }]}:null,loading:false,error:'',retry:()=>{}});
    try{
      const html=render(React.createElement(TaskTermsPanel,{
        task:{...task,status:status==='approved'?'cancelled':'in_progress'},user:viewer,onChange:()=>{},
      }));
      assert.ok(html.includes(expectedAction),html);
      assert.ok(html.includes('<strong>取消结算金额</strong>'),html);
      assert.ok(html.includes('<p style="white-space:pre-wrap">¥25.50</p>'),html);
      assert.ok(!html.includes('阶段完成要求'),html);
    }finally{live.useLiveResource=original;}
  });
}
