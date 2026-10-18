import {memo} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './markdown.css';

// Render a React syntax tree: model output never becomes executable HTML.
export const MarkdownReply=memo(function MarkdownReply({text,className=''}:{text:string;className?:string}){
  return <div className={`markdown-reply ${className}`}><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    h1:({children})=><h3>{children}</h3>,
    h2:({children})=><h4>{children}</h4>,
    a:({href,children})=><a href={href} target={href?.startsWith('#')?undefined:'_blank'} rel="noopener noreferrer">{children}</a>,
    img:({src,alt})=><a href={src} target="_blank" rel="noopener noreferrer">{alt||'查看图片'}</a>,
    table:({children})=><div className="markdown-table"><table>{children}</table></div>,
  }}>{text}</ReactMarkdown></div>;
});
