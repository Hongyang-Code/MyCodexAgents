// Synthetic/public acceptance artifacts. Supply bundled runtime paths via environment.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const {SKILL_DIR, RUNTIME_NODE_MODULES, RUNTIME_PYTHON, PPTMAKER_RUN} = process.env;
for (const value of [SKILL_DIR, RUNTIME_NODE_MODULES, RUNTIME_PYTHON, PPTMAKER_RUN]) {
  if (!value || !path.isAbsolute(value)) throw new Error('Supply absolute runtime and run paths');
}
const req = createRequire(path.join(RUNTIME_NODE_MODULES, 'package.json'));
const {Presentation, PresentationFile, FileBlob} = await import(pathToFileURL(req.resolve('@oai/artifact-tool')).href);
const helper = await import(pathToFileURL(path.join(SKILL_DIR, 'container_tools/artifact_tool_utils.mjs')).href);
const family = helper.resolvePresentationFont({fontFamily: process.env.PPTMAKER_FONT || 'Microsoft YaHei'});
const ink='#203348', accent='#176B78', muted='#506575';
const root=path.resolve(PPTMAKER_RUN);
await fs.mkdir(root,{recursive:true});
function text(slide,name,value,x,y,w,h,size=28,color=ink,bold=false){
  const s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  s.text=value; s.text.style={typeface:family,fontSize:size,color,bold,autoFit:'none'}; return s;
}
function page(p,title,idx){
  const s=p.slides.add(); s.background.fill='#F8FAFB';
  text(s,'title',title,72,52,1120,86,44,ink,true);
  text(s,'page-number',String(idx).padStart(2,'0'),1140,651,68,34,20,muted);
  return s;
}
function para(s,value,y=200){ return text(s,'body-'+y,value,76,y,1100,95,30); }
async function render(p,dir){
  await fs.mkdir(dir,{recursive:true});
  for(let i=0;i<p.slides.items.length;i++){
    const slide=p.slides.items[i];
    const png=await p.export({slide,format:'png',scale:1});
    await fs.writeFile(path.join(dir,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
    const layout=await slide.export({format:'layout'});
    await fs.writeFile(path.join(dir,`slide-${i+1}.layout.json`),await layout.text());
  }
}
async function finish(p,mode,{tables=[],charts=[]}={}){
  const run=path.join(root,mode); await fs.mkdir(path.join(run,'.cache'),{recursive:true});
  await fs.mkdir(path.join(run,'delivery'),{recursive:true});
  const suffix=process.env.PPTMAKER_VERSION ? '-'+process.env.PPTMAKER_VERSION : '';
  const candidate=path.join(run,'.cache',`candidate${suffix}.pptx`), final=path.join(run,'delivery',`presentation${suffix}.pptx`);
  await (await PresentationFile.exportPptx(p)).save(candidate);
  const result=await helper.finalizePresentation({workspaceDir:run,candidatePath:candidate,finalPath:final,
    pythonExecutable:RUNTIME_PYTHON,
    integrityValidatorPath:path.join(SKILL_DIR,'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath:path.join(SKILL_DIR,'container_tools/inspect_presentation_layout_geometry.py'),
    layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
    explicitTotalSlideCount:p.slides.items.length, requiredNativeTableOwnerSlides:tables,
    requiredNativeChartOwnerSlides:charts, materializeLiteralChartWorkbooks:charts.length>0,
    fontPolicy:{basis:'design',families:[family]},verifyArtifactToolImport:true,
    receiptPath:path.join(run,'.cache',`finalizer${suffix}.json`)});
  await fs.writeFile(path.join(run,'.cache',`finalizer-result${suffix}.json`),JSON.stringify(result,null,2));
  const imported=await PresentationFile.importPptx(await FileBlob.load(final));
  await render(imported,path.join(run,'delivery',`preview${suffix}`));
  await fs.writeFile(path.join(run,'.cache',`inspect${suffix}.ndjson`),(await imported.inspect({kind:'slide,textbox,shape,chart,table,notes,layout',maxChars:50000})).ndjson);
  console.log(mode+': '+final);
}
const phase=process.argv[2]||'source';
if(phase==='source'){
  const p=Presentation.create({slideSize:{width:1280,height:720}});
  const s1=page(p,'旧项目进展',1); para(s1,'旧结论：结果待更新',215);
  text(s1,'fixed-lab','科研方法交流',76,649,650,36,20,muted);
  s1.speakerNotes.textFrame.setText('旧备注需要替换。合成模板，无真实研究结论。');
  const s2=page(p,'旧实验设置',2); para(s2,'旧数据：训练20例，测试5例',215);
  text(s2,'fixed-lab','科研方法交流',76,649,650,36,20,muted);
  s2.speakerNotes.textFrame.setText('旧方法说明。合成模板。');
  const dir=path.join(root,'source');await fs.mkdir(dir,{recursive:true});
  await (await PresentationFile.exportPptx(p)).save(path.join(dir,'template.pptx'));
  await render(p,path.join(dir,'preview'));
  console.log((await p.inspect({kind:'slide,textbox,shape,layout',maxChars:15000})).ndjson);
} else if(phase==='template'){
  const p=await PresentationFile.importPptx(await FileBlob.load(path.join(root,'source','template.pptx')));
  const snap=await p.inspect({kind:'slide,textbox,shape',maxChars:20000});
  await fs.writeFile(path.join(root,'source','import-inspect.ndjson'),snap.ndjson);
  // Edit imported shapes by their observed content, preserving positions and styles.
  const replacements=new Map([['旧项目进展','配准实验进展（合成示例）'],['旧结论：结果待更新','平均 Dice 从 0.80 增至 0.82\n仅反映本次测试集结果'],['旧实验设置','训练与测试保持分离'],['旧数据：训练20例，测试5例','训练 40 例，测试 10 例\n未开展跨中心验证']]);
  const found=new Set();
  for(const slide of p.slides.items){
    for(const sh of slide.shapes.items){
      for(const [old,next] of replacements){
        const value=sh.text?.toString();
        if(value===old){sh.text.replace(old,next); found.add(old);}
      }
    }
  }
  if(found.size!==replacements.size) throw new Error('Cannot resolve all imported source objects: '+JSON.stringify([...found]));
  p.slides.items[0].speakerNotes.textFrame.setText('合成案例，仅用于PPT流程验证。相同测试集的平均Dice为0.80与0.82，未做显著性检验，不能据此声称普遍改善。');
  p.slides.items[1].speakerNotes.textFrame.setText('合成实验设置：训练40例，测试10例，二者互不重叠。尚未开展跨中心验证，不能外推到其他中心。');
  await finish(p,'template');
} else if(phase==='materials'){
  const p=Presentation.create({slideSize:{width:1280,height:720}});
  const s1=page(p,'配准方法的两步流程',1);
  para(s1,'合成案例：先估计对应关系，再生成配准结果',158);
  const a=text(s1,'input-node','输入图像',100,320,240,82,32,accent,true);
  const b=text(s1,'matching-node','估计对应关系',480,320,280,82,32,accent,true);
  const c=text(s1,'output-node','生成配准结果',890,320,300,82,32,accent,true);
  s1.shapes.connect(a,b,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:accent,width:3},tail:{type:'triangle'}});
  s1.shapes.connect(b,c,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:accent,width:3},tail:{type:'triangle'}});
  text(s1,'scope','流程仅用于说明，不代表已实现的新方法',76,534,1090,68,26,muted);
  s1.speakerNotes.textFrame.setText('来源：本次合成材料。输入为图像对，第一步估计对应关系，第二步由对应关系生成配准结果。未运行方法或实验。');
  const s2=page(p,'合成结果与证据边界',2);
  const table=s2.tables.add({rows:3,columns:3,left:76,top:180,width:570,height:234,values:[['方法','平均 Dice','测试集'],['基线','0.80','相同10例'],['候选','0.82','相同10例']]});
  table.cells.block({row:0,column:0,rowCount:3,columnCount:3}).assign({textStyle:{typeface:family,fontSize:27,color:ink},fill:'#FFFFFF',margins:{left:12,right:12,top:10,bottom:10}});
  table.cells.block({row:0,column:0,rowCount:1,columnCount:3}).assign({fill:accent,textStyle:{color:'#FFFFFF',bold:true}});
  const chart=s2.charts.add('bar',{position:{left:700,top:166,width:480,height:310},categories:['基线','候选'],series:[{name:'平均 Dice',values:[0.80,0.82],valuesFormatCode:'0.00',fill:accent}],hasLegend:false,barOptions:{direction:'column',grouping:'clustered'},xAxis:{textStyle:{fontSize:22,fill:ink}},yAxis:{min:0,max:1,majorUnit:0.5,numberFormatCode:'0.00',textStyle:{fontSize:22,fill:ink}},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:23,fill:ink}},title:'平均 Dice',titleTextStyle:{fontSize:27,fill:ink}});
  helper.applyPresentationChartFont(chart,{fontFamily:family});
  text(s2,'limit','差值为 0.02；未做显著性检验\n本页为合成数据，不构成研究证据',76,493,1090,99,28,muted);
  s2.speakerNotes.textFrame.setText('来源：本次合成材料。训练40例，测试10例。两种方法使用相同测试集。平均Dice为0.80和0.82，差值0.02。未做显著性检验或跨中心验证。');
  const s3=page(p,'成品截图保留原貌',3);
  s3.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'source','preview','slide-1.png'))),contentType:'image/png',alt:'合成模板的原始页面截图，按成品图片使用',fit:'contain',position:{left:80,top:176,width:760,height:428}});
  text(s3,'image-explanation','原图直接插入\n外部说明可编辑\n无需拆解图内文字',900,254,300,210,28,muted);
  s3.speakerNotes.textFrame.setText('来源：本次生成的合成模板页面截图。截图中的旧项目字样属于原图内容，按成品图片保留，不表示本次实验事实。页面标题和右侧说明为原生可编辑文字。');
  await finish(p,'materials',{tables:[2],charts:[2]});
} else if(phase==='topic'){
  const p=Presentation.create({slideSize:{width:1280,height:720}});
  const src='https://scikit-learn.org/stable/common_pitfalls.html#data-leakage';
  let s=page(p,'预处理也可能泄漏测试信息',1);
  para(s,'先划分数据，再拟合预处理步骤',196);
  para(s,'测试集不参与均值估计、特征选择或模型选择',317);
  text(s,'cite','来源：scikit-learn 官方文档，Common pitfalls §12.2',76,556,1100,55,22,muted);
  s.speakerNotes.textFrame.setText('在标准留出评估中，预处理统计量仅从训练子集学习。测试集使用已拟合的变换。若测试信息参与构建模型，性能估计可能过于乐观。来源：'+src+'，访问日期2026-10-02。');
  s=page(p,'交叉验证中的拟合范围',2);
  para(s,'每一折只在训练子集内拟合预处理和模型',196);
  para(s,'Pipeline 可将预处理与模型纳入同一评估流程',317);
  text(s,'limit','Pipeline 不能替代对数据划分方式的检查',76,455,1100,70,28,muted);
  text(s,'cite','来源：scikit-learn 官方文档，Common pitfalls；Cross-validation',76,565,1100,50,22,muted);
  s.speakerNotes.textFrame.setText('Pipeline有助于在交叉验证中将fit限制在相应训练子集。数据存在同一对象的重复观测时，应根据泛化目标检查分组划分。工具不能自动决定正确的分组单位。来源：'+src+'；https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data，访问日期2026-10-02。');
  await finish(p,'topic');
} else throw new Error('Unknown phase');
