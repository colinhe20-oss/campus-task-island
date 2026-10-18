const assert=require('node:assert/strict');const {test}=require('node:test');const fs=require('node:fs');const ts=require('typescript');
for(const ext of ['.ts','.tsx'])require.extensions[ext]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,file);
require.extensions['.css']=()=>{};
const React=require('react');const {renderToStaticMarkup}=require('react-dom/server');const {PlanningReview}=require('../src/PlanningReview.tsx');
const render=plan=>renderToStaticMarkup(React.createElement(PlanningReview,{plan,conversation:'demo',version:2,disabled:false,onChange:()=>{},onReview:()=>{}}));
const base={kind:'volunteer',fields:{title:'测试'},status:'draft',ready:false,issues:[],checks:[{code:'headcount_mismatch',path:'target_volunteers',message:'计划招募20人，岗位合计12人'}],changes:[{path:'fields.ends_at',label:'ends_at',before:'14:00',after:'15:00'}],impacts:[{message:'摄影岗时段超出活动范围'}]};
test('确定性错误、修改差异和影响分别显示',()=>{const html=render(base);for(const text of ['方案检查','需修复','本次修改','修改前','修改后','确定影响','摄影岗'])assert.ok(html.includes(text),text);});
test('采纳前显示拟修改字段和人数，过期建议禁止采纳',()=>{
 const html=render({...base,review:{base_version:1,stale:true,questions:['集合地点？'],rechecks:['核对设备'],proposals:[{id:'p',title:'分工建议',reason:'依据活动目标',evidence:[{path:'fields.title',value:'测试'}],fields:{description:'新的安排'},target_volunteers:20,status:'pending'}]}});
 for(const text of ['已过期','拟修改的字段','计划招募总人数','20','新的安排','建议依据'])assert.ok(html.includes(text),text);
 assert.match(html,/<button disabled="" class="button">采纳到草稿<\/button>/);
});
