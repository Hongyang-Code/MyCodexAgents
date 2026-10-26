// Reimport the exact PPTX and render all slides. This is not a visual approval.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const [inputArg,outputArg]=process.argv.slice(2);
if(!inputArg || !outputArg || !process.env.RUNTIME_NODE_MODULES) throw new Error('Usage: render_deck.mjs <pptx> <new-preview-directory>; supply RUNTIME_NODE_MODULES');
const input=path.resolve(inputArg), output=path.resolve(outputArg);
await fs.mkdir(output,{recursive:false}); // Never overwrite a previously reviewed preview directory.
const req=createRequire(path.join(process.env.RUNTIME_NODE_MODULES,'package.json'));
const {PresentationFile,FileBlob}=await import(pathToFileURL(req.resolve('@oai/artifact-tool')).href);
const p=await PresentationFile.importPptx(await FileBlob.load(input));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const manifest={pptx_sha256:sha(await fs.readFile(input)),slides:[]};
for(let i=0;i<p.slides.items.length;i++){
 const png=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 const bytes=new Uint8Array(await png.arrayBuffer()), name=`slide-${i+1}.png`;
 await fs.writeFile(path.join(output,name),bytes);
 manifest.slides.push({page:i+1,image:name,sha256:sha(bytes)});
}
await fs.writeFile(path.join(output,'render-manifest.json'),JSON.stringify(manifest,null,2));
const overview=await p.export({format:'webp',montage:true,scale:2});
await fs.writeFile(path.join(output,'overview.webp'),new Uint8Array(await overview.arrayBuffer()));
console.log(JSON.stringify({rendered:manifest.slides.length,output,visual_review:'not_performed'}));
