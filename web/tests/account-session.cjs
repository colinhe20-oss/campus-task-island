const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require('typescript');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(
  ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
require.extensions['.css']=()=>{};
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {AccountPage,RegisterPage}=require('../src/Accounts.tsx');
const {clearAccountSessionCache}=require('../src/session.ts');
const user={id:'user-a',username:'alice',display_name:'同学甲',can_publish_activities:true,can_publish_volunteers:true};
const html=renderToStaticMarkup(React.createElement(AccountPage,{user}));
assert.ok(html.includes('账号信息')&&html.includes('alice')&&html.includes('同学甲'));
assert.ok(html.includes('退出登录')&&html.includes('记录会继续保留'));
assert.ok(!html.includes('<form')&&!html.includes('注销')&&!html.includes('不可恢复'));
const register=renderToStaticMarkup(React.createElement(RegisterPage,{onRegister:()=>{}}));
assert.ok(!register.includes('注销'));
const storage={
  'campus-guide-conversation:user-a':'conversation-a',
  'campus-guide-run:user-a':'run-a',
  'campus-stage-run:user-a:task-1':'stage-run-a',
  'campus-guide-conversation:user-b':'conversation-b',
  'campus-stage-run:user-a-other:task-1':'other-account-run',
  unrelated:'preserve',
};
Object.defineProperty(storage,'removeItem',{value(key){delete this[key];}});
global.sessionStorage=storage;
clearAccountSessionCache('user-a');
assert.deepEqual(Object.keys(storage).sort(),[
  'campus-guide-conversation:user-b','campus-stage-run:user-a-other:task-1','unrelated',
].sort());
Object.defineProperty(global,'sessionStorage',{configurable:true,get(){throw new Error('Storage disabled');}});
assert.doesNotThrow(()=>clearAccountSessionCache('user-a'));
console.log('PASS: account page, registration copy, private recovery cache cleanup and disabled storage');
