const assert=require('node:assert/strict');
const {test}=require('node:test');
const path=require('node:path');
const {buildSync}=require('esbuild');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const bundle=buildSync({entryPoints:[path.resolve(__dirname,'../src/MarkdownReply.tsx')],bundle:true,platform:'node',format:'cjs',write:false,
  external:['react','react-dom'],loader:{'.css':'empty'},jsx:'automatic'}).outputFiles[0].text;
const compiled={exports:{}};
new Function('require','module','exports',bundle)(require,compiled,compiled.exports);
const {MarkdownReply}=compiled.exports;
const render=text=>renderToStaticMarkup(React.createElement(MarkdownReply,{text}));

test('回复按段落、粗体、行内代码和列表渲染',()=>{
 const html=render('评估已记录，`target_volunteers` 仍为空。结果见**方案检查与建议卡片**。\n\n1. 核对时间\n2. 补齐岗位');
 assert.match(html,/<code>target_volunteers<\/code>/);
 assert.match(html,/<strong>方案检查与建议卡片<\/strong>/);
 assert.match(html,/<ol>/);assert.match(html,/<li>核对时间<\/li>/);
 assert.ok(!html.includes('**方案检查'));
});
test('表格、引用和代码块保持正确结构',()=>{
 const html=render('## 岗位安排\n\n| 岗位 | 人数 |\n| --- | --- |\n| 清洁 | 12 |\n\n> 请核对\n\n```python\nprint("hello")\n```');
 assert.match(html,/<h4>岗位安排<\/h4>/);assert.match(html,/<table>/);assert.match(html,/<blockquote>/);
 assert.match(html,/<pre><code class="language-python">/);
});
test('模型返回的 HTML、脚本和危险链接不能执行',()=>{
 const html=render('<script>alert("bad")</script>\n\n<img src="x" onerror="alert(1)">\n\n[危险链接](javascript:alert%281%29)\n\n[正常链接](https://example.com)\n\n![参考图片](https://example.com/image.png)');
 assert.ok(!html.includes('<script')&&!html.includes('<img')&&!html.includes('onerror')&&!html.includes('javascript:'));
 assert.ok(html.includes('href="https://example.com"')&&html.includes('rel="noopener noreferrer"'));
 assert.ok(html.includes('参考图片'));
});
test('纯文本和未闭合的流式 Markdown 仍可显示',()=>{
 assert.ok(render('一条普通回复').includes('一条普通回复'));
 for(const text of ['**正在整理','```python\nprint(1)','- 待确认'])assert.ok(render(text).length>0);
});
