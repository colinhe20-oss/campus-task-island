const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const ts=require('typescript');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(
  ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
require.extensions['.css']=()=>{};
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {RunTrace}=require('../src/RunTrace.tsx');
const render=(events,status='succeeded')=>renderToStaticMarkup(React.createElement(RunTrace,{events,status,names:{search_tasks:'搜索任务'}}));
const event=(seq,kind,other={})=>({seq,kind,step:1,at:`2026-10-17T00:00:0${seq}+00:00`,...other});

test('同轮重复工具按调用ID对应耗时和错误',()=>{
 const html=render([event(1,'tool_started',{tool:'search_tasks',call_id:'one'}),event(2,'tool_finished',{tool:'search_tasks',call_id:'one',duration_ms:23,success:true}),event(3,'tool_started',{tool:'search_tasks',call_id:'two'}),event(4,'tool_finished',{tool:'search_tasks',call_id:'two',duration_ms:67,success:false})]);
 assert.ok(html.includes('23 ms')&&html.includes('67 ms'));
 assert.ok(html.includes('失败')&&html.includes('完成'));
 assert.ok(!html.includes('NaN'));
});
test('取消和失败的未结束调用不会被标记为执行中',()=>{
 for(const status of ['cancelled','failed','interrupted']){
  const html=render([event(1,'model_started')],status);
  assert.ok(html.includes('已中止'));assert.ok(!html.includes('执行中'));
 }
});
test('运行中显示工具活动状态且空轨迹可读',()=>{
 assert.ok(render([event(1,'tool_started',{tool:'search_tasks',call_id:'one'})],'running').includes('执行中'));
 assert.ok(render([]).includes('发送问题后显示'));
});
