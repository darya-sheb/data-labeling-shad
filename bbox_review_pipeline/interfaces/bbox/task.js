function inherit(Parent, methods) { function Child(options) { Parent.call(this, options); } Child.prototype=Object.create(Parent.prototype); Object.keys(methods).forEach(function(k){Child.prototype[k]=methods[k];}); Child.prototype.constructor=Child; return Child; }
function bfBox(a){if(!a||a.type!=='rectangle'||!a.data||!a.data.p1||!a.data.p2)return null;var p=a.data.p1,q=a.data.p2,b=[Math.min(p.x,q.x),Math.min(p.y,q.y),Math.max(p.x,q.x),Math.max(p.y,q.y)];return b.every(function(v){return typeof v==='number'&&isFinite(v)&&v>=0&&v<=1;})&&b[2]>b[0]&&b[3]>b[1]?b:null;}
function bfIoU(a,b){var w=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0])),h=Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1])),i=w*h;return i/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-i);}
function bfRect(svg,b,color){var r=document.createElementNS('http://www.w3.org/2000/svg','rect');['x','y','width','height'].forEach(function(k,i){r.setAttribute(k,[b[0]*1000,b[1]*1000,(b[2]-b[0])*1000,(b[3]-b[1])*1000][i]);});r.setAttribute('stroke',color);r.setAttribute('stroke-width','3');r.setAttribute('vector-effect','non-scaling-stroke');r.setAttribute('fill','none');svg.appendChild(r);return r;}
function bfLayer(container,name){var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add(name);svg.setAttribute('viewBox','0 0 1000 1000');svg.setAttribute('preserveAspectRatio','none');container.appendChild(svg);return svg;}

function bfCorrectionNotice(root, input, editor, readOnly, selectFrame) {
 var panel = root.querySelector('.bf-correction');
 if (!panel) return null;
 var feedback = input.correction_feedback;
 var title = panel.querySelector('strong'), hint = panel.querySelector('p');
 var progress = panel.querySelector('small'), next = panel.querySelector('button');
 function key(box) { return box && box.map(function(v) { return Math.round(v * 1000000); }).join(','); }
 function position(shape) { return key(bfBox(shape)); }
 var originalShapes = (editor.shapes || []).slice();
 var entries = (input.editable_annotations || []).map(function(shape, i) {
  var start = position(shape);
  var match = originalShapes.findIndex(function(s) { return position(s) === start; });
  var original = match < 0 ? null : originalShapes.splice(match, 1)[0];
  var reason = (feedback.geometry_frames || []).includes(i + 1) ? 'Неточные границы' :
               (feedback.disputed_frames || []).includes(i + 1) ? 'Проверяющие разошлись в оценке' : 'Проверьте выделение';
  // An original already changed or removed in a restored draft has no unchanged shape to visit.
  return {start:start, shape:original, reason:reason, visited:!original && Array.isArray(editor.shapes)};
 });
 var fixed = new Set((input.fixed_boxes || []).map(function(b) { return key(b.bbox || b); }));
 var starts = new Set(entries.map(function(e) { return e.start; }));
 var restoredExtra = originalShapes.length > 0 && (editor.shapes || []).length > entries.length;
 var drawn = new WeakSet(), selected = null, pendingEditors = [];
 function entryFor(shape) {
  return entries.find(function(e) { return e.shape === shape; }) || entries.find(function(e) { return e.start === position(shape); });
 }
 function markNew(shape) { drawn.add(shape); }
 function imageReady() { check(editor.shapes); }
 function activate(s) {
  selected = s && !s.isNewShape() ? entryFor(s.shape) : null;
  if (selected) selected.visited = true;
  check(editor.shapes);
 }
 function check(shapes, emptyConfirmed) {
  shapes = shapes || [];
  var empty = root.querySelector('.bf-empty-check');
  if (emptyConfirmed === undefined) emptyConfirmed = empty.checked;
  var keys = shapes.map(position);
  var pending = entries.filter(function(e) { return !e.visited || keys.includes(e.start); });
  pendingEditors = [];
  (editor._shapeEditors || []).forEach(function(s) {
   var entry = entryFor(s.shape), unfinished = pending.includes(entry);
   var rect = s._el.rect && s._el.rect.el;
   if (rect) rect.classList.toggle('bf-needs-review', unfinished && entry !== selected);
   if (unfinished) pendingEditors.push(s);
  });
  var message = '';
  var canConfirmEmpty = feedback.coverage === 'missing_yes' && !feedback.redraw_after_duplicate &&
                        !input.practice && !pending.length && !shapes.length;
  var emptyClaim = canConfirmEmpty && emptyConfirmed === true;
  var heading, detail;
  if (pending.length) {
   heading = 'ПРОВЕРЬТЕ КАЖДУЮ ОРАНЖЕВУЮ РАМКУ';
   if (pending.includes(selected)) {
    detail = selected.reason === 'Неточные границы' ? 'Подведите стороны к кончикам крыльев, усиков и лапок. Проверьте, не обрезан ли край и нет ли широкой полосы фона.' : 'Проверьте, что выделена одна бабочка целиком. Поправьте границы или удалите лишнюю рамку.';
    message = 'Исправьте выбранную рамку или удалите её, если она лишняя.';
   } else {
    detail = 'Нажмите Enter или кликните у края мигающей рамки, чтобы увидеть замечание.';
    message = 'Остались оранжевые рамки для исправления.';
   }
  } else {
   var missing = feedback.coverage === 'missing_yes';
   var newPositions = new Set((editor.shapes || []).filter(function(s) { return drawn.has(s); }).map(position));
   var distinct = new Set(keys.filter(function(k) { return k && !fixed.has(k); }));
   var extra = (restoredExtra || !Array.isArray(editor.shapes)) && distinct.size > entries.length;
   var added = keys.some(function(k) { return k && !starts.has(k) && !fixed.has(k) && keys.indexOf(k) === keys.lastIndexOf(k) && (newPositions.has(k) || extra); });
   if (missing && !added && !emptyClaim) {
    heading = 'Выделите пропущенных бабочек';
    detail = canConfirmEmpty ? 'Осмотрите всё фото. Если увидите бабочку без рамки, нажмите B и обведите её. Если таких бабочек нет, отметьте это ниже.' : 'Нажмите B и обведите каждую бабочку без рамки отдельно.';
    message = 'Добавьте по одной рамке для каждой пропущенной бабочки.';
   } else if (feedback.redraw_after_duplicate && !fixed.size && !distinct.size) {
    heading = 'Обведите бабочку заново';
    detail = 'После удаления повтора у бабочки не осталось рамки. Нажмите B и обведите её целиком.';
    message = 'Добавьте рамку вокруг бабочки.';
   } else {
    heading = 'Проверьте фото целиком';
    detail = missing ? 'Убедитесь, что у каждой бабочки есть своя рамка, и подтвердите просмотр фото.' : feedback.redraw_after_duplicate ? 'Повтор удалён. Проверьте, что у каждой бабочки осталась своя рамка.' : 'Если найдёте бабочек без рамок, обведите каждую отдельно. Затем подтвердите просмотр фото.';
   }
  }
  var readyToConfirm = selected && !pending.includes(selected);
  if (readyToConfirm) {
   heading = 'Рамка исправлена';
   detail = pending.length ? 'Нажмите Enter, чтобы перейти к следующей рамке с замечанием.' : 'Нажмите Enter, затем осмотрите фото целиком.';
  }
  var label = panel.querySelector('.bf-frame-reason');
  var reason = pending.includes(selected) ? selected.reason : '';
  if (label.textContent !== reason) label.textContent = reason;
  label.hidden = !reason;
  if (title.textContent !== heading) title.textContent = heading;
  if (hint.textContent !== detail) hint.textContent = detail;
  var count = 'Исправлено ' + (entries.length - pending.length) + ' из ' + entries.length;
  if (progress.textContent !== count) progress.textContent = count;
  progress.hidden = !entries.length;
  next.hidden = !selected && !pendingEditors.length;
  next.disabled = readOnly || pending.includes(selected);
  next.querySelector('span').textContent = selected ? 'Подтвердить рамку' : 'Выбрать рамку';
  root.querySelector('.bf-review-confirmation').hidden = !!message || !!readyToConfirm;
  root.querySelector('.bf-reviewed').disabled = !!message || readOnly;
  var emptyLabel = root.querySelector('.bf-empty');
  emptyLabel.hidden = shapes.length > 0 || (!!message && !canConfirmEmpty);
  if (canConfirmEmpty) emptyLabel.querySelector('span').textContent = fixed.size ?
   'Я проверил(а) всё фото. Все бабочки уже в красных рамках' : 'Я проверил(а) всё фото. Бабочек нет';
  if (panel.dataset.issue && panel.dataset.issue !== message) {
   var error = root.querySelector('.bf-error');
   if (error.textContent === panel.dataset.issue) { error.hidden = true; error.textContent = ''; }
  }
  panel.dataset.issue = message;
  return message;
 }
 function advanceFrame() {
  if (!selected && !pendingEditors.length) return false;
  if (pendingEditors.includes(editor._activeShapeEditor)) {
   hint.textContent = 'Сначала поправьте границы. Если рамка лишняя, удалите её клавишей Del.';
  } else {
   selectFrame(pendingEditors[0] || null);
  }
  return true;
 }
 next.onclick = advanceFrame;
 editor.on('shape:editor:activated', activate);
 editor.on('image:load', imageReady);
 editor.on('shape:finish', markNew);
 return {check:check, advanceFrame:advanceFrame, destroy:function() {
  editor.removeListener('shape:editor:activated', activate);
  editor.removeListener('image:load', imageReady);
  editor.removeListener('shape:finish', markNew);
 }};
}

/* Adapter for the official editor. Keep selection changes and shape updates in
   its event pipeline; coordinates always stay normalized to the original image. */
function BFBBoxControls(task,editor,root,container,viewport){
 var self=this,win=root.ownerDocument.defaultView,overlay=bfLayer(container,'bf-edge-overlay'),drag=null,down=null,panMode=false,draw=null,suppressClick=false;
 var add=root.querySelector('.bf-add'),remove=root.querySelector('.bf-delete'),cancel=root.querySelector('.bf-cancel'),pan=root.querySelector('.bf-pan'),status=root.querySelector('.bf-status');
 var zoomHint=root.querySelector('.bf-zoom-hint');
 function needsMagnification(box){
  if(!box)return false;
  var area=(box[2]-box[0])*(box[3]-box[1]);
  return area<=0.03 && area*task._zoom.scale*task._zoom.scale<=0.03;
 }
 this.active=function(){return task._zoom.active()&&!task.getWorkspaceOptions().isReadOnly;};
 this.clear=function(){suppressClick=false;draw=null;drag=null;down=null;panMode=false;task._zoom.adapter.nativePan=true;if(editor._activeShapeEditor){if(editor._activeShapeEditor.isNewShape())editor._onShapeCancel(editor._activeShapeEditor);else editor._activateShapeEditor(null);}if(editor.hideAnnotation)editor.hideAnnotation();self.refresh();};
 this.finish=function(){var selected=editor._activeShapeEditor;if(selected&&selected.isNewShape()&&selected._el.rect){var p=selected._el.rect.p1,q=selected._el.rect.p2;if(p&&q&&bfBox({type:'rectangle',data:{p1:p,p2:q}})){var r=container.getBoundingClientRect();selected._onMouseUp(self.drawEvent({clientX:r.left+q.x*r.width,clientY:r.top+q.y*r.height}));}}self.clear();};
 this.add=function(){if(!self.active())return;var wasNew=editor._activeShapeEditor&&editor._activeShapeEditor.isNewShape();self.clear();if(!wasNew){var button=root.querySelector('.image-annotation-editor__shape-rectangle');if(button)button.click();}self.refresh();};
 this.pan=function(){if(!self.active())return;var enabled=!panMode;self.clear();panMode=enabled;task._zoom.adapter.nativePan=!panMode;self.refresh();};
 this.select=function(shape){if(!self.active())return;if(editor._activeShapeEditor===shape){self.clear();return;}self.clear();editor._onShapeActivate(shape);shape._el.rect.activate();self.refresh();};
 this.shapeFinish=function(shape){var created=(editor._shapeEditors||[]).find(function(s){return s.shape===shape;});if(created&&self.active())self.select(created);};
 this.remove=function(){if(!self.active())return;var selected=editor._activeShapeEditor;if(!selected)return;if(selected.isNewShape())self.clear();else selected.removeFromCanvas();self.refresh();};
 // Hit-test in screen pixels so filled interiors never hide nested frames.
 this.shapeAt=function(e){
  var r=container.getBoundingClientRect(),best=null,bestDistance=Infinity,bestArea=Infinity;
  if(!r.width||!r.height)return null;
  (editor._shapeEditors||[]).forEach(function(shape){var b=bfBox(shape.shape);if(!b)return;
   var left=r.left+b[0]*r.width,right=r.left+b[2]*r.width,top=r.top+b[1]*r.height,bottom=r.top+b[3]*r.height;
   var x=e.clientX,y=e.clientY,dx=Math.max(left-x,0,x-right),dy=Math.max(top-y,0,y-bottom);
   var distance=dx||dy?Math.hypot(dx,dy):Math.min(x-left,right-x,y-top,bottom-y),area=(right-left)*(bottom-top);
   if(distance<=6&&(distance<bestDistance||distance===bestDistance&&area<bestArea)){best=shape;bestDistance=distance;bestArea=area;}
  });return best;
 };
 this.refresh=function(){
  (editor._shapeEditors||[]).forEach(function(shape){var rect=shape._el&&shape._el.rect&&shape._el.rect.el;if(!rect||!rect.parentNode)return;var halo=rect.parentNode.querySelector('.bf-edit-halo');if(!halo){halo=rect.cloneNode(false);halo.setAttribute('class','bf-edit-halo');halo.style.pointerEvents='none';rect.parentNode.insertBefore(halo,rect);}['x','y','width','height'].forEach(function(k){halo.setAttribute(k,rect.getAttribute(k));});});
  overlay.textContent='';var selected=editor._activeShapeEditor,isNew=selected&&selected.isNewShape(),box=selected&&!isNew?bfBox(selected.shape):null;
  var editable=editor.shapes||task.getSolution().output_values.result||[];
  zoomHint.hidden=task.getWorkspaceOptions().isReadOnly || !(box ? needsMagnification(box) : editable.some(function(shape){return needsMagnification(bfBox(shape));}));
  add.setAttribute('aria-pressed',isNew?'true':'false');remove.disabled=!box||!self.active();cancel.disabled=!selected&&!panMode;pan.setAttribute('aria-pressed',panMode?'true':'false');
  status.textContent=panMode?'Перетаскивайте фото мышью · V / Esc — выход · B — нарисовать рамку':isNew?'Укажите второй угол или протяните мышью · Esc — отмена':box?'Выбрана рамка · Углы и стороны — изменить размер · Del — удалить · Enter / Esc / повторный клик — закончить':'Левая кнопка — рамка · Правая / пробел — двигать фото · Колесо — прокрутка · Ctrl/⌘ + колесо или щипок — масштаб';
  if(task._correctionNotice && box && !panMode)status.textContent='Потяните сторону или угол · Enter — подтвердить правку · Del — удалить · Esc — снять выделение';
  var list=root.querySelector('.bf-box-list'),fixed=task.getTask().input_values.fixed_boxes||[],shapes=editor._shapeEditors||[];if(list)list.textContent='';root.querySelector('.bf-box-count').textContent='Оранжевые: '+(editor.shapes||task.getSolution().output_values.result||[]).length+(fixed.length?' · уже приняты: '+fixed.length:'');if(list){shapes.forEach(function(s,i){var b=document.createElement('button');b.type='button';b.textContent='▢ Рамка '+(i+1);b.setAttribute('aria-pressed',s===selected?'true':'false');b.disabled=!self.active();b.onclick=function(){self.select(s);};list.appendChild(b);});fixed.forEach(function(s,i){var b=document.createElement('button');b.type='button';b.className='bf-locked';b.textContent='▣ Зафиксировано '+(i+1);b.title='Уже проверено — эту рамку нельзя двигать или изменять';b.setAttribute('aria-disabled','true');list.appendChild(b);});}
  if(!box||!self.active())return;
  var width=container.getBoundingClientRect().width||1000,height=container.getBoundingClientRect().height||1000,dx=Math.min((box[2]-box[0])*250,9/width*1000),dy=Math.min((box[3]-box[1])*250,9/height*1000);
  var sides=[['left',box[0]*1000,box[1]*1000+dy,box[0]*1000,box[3]*1000-dy],['right',box[2]*1000,box[1]*1000+dy,box[2]*1000,box[3]*1000-dy],['top',box[0]*1000+dx,box[1]*1000,box[2]*1000-dx,box[1]*1000],['bottom',box[0]*1000+dx,box[3]*1000,box[2]*1000-dx,box[3]*1000]];
  sides.forEach(function(s){var line=document.createElementNS('http://www.w3.org/2000/svg','line');['x1','y1','x2','y2'].forEach(function(k,i){line.setAttribute(k,s[i+1]);});line.setAttribute('stroke','transparent');line.setAttribute('stroke-width','14');line.setAttribute('vector-effect','non-scaling-stroke');line.style.pointerEvents='stroke';line.style.cursor=s[0]==='left'||s[0]==='right'?'ew-resize':'ns-resize';line.dataset.edge=s[0];overlay.appendChild(line);
   var dot=document.createElementNS('http://www.w3.org/2000/svg','rect');dot.setAttribute('x',(s[1]+s[3])/2-3.5/width*1000);dot.setAttribute('y',(s[2]+s[4])/2-3.5/height*1000);dot.setAttribute('width',7/width*1000);dot.setAttribute('height',7/height*1000);dot.setAttribute('fill','#fff');dot.setAttribute('stroke','#d96c00');dot.setAttribute('vector-effect','non-scaling-stroke');dot.style.pointerEvents='none';overlay.appendChild(dot);
  });
 };
 this.edgeDown=function(e){var edge=e.target.dataset.edge;if(!edge||e.button!==0||!self.active())return;var selected=editor._activeShapeEditor;if(!selected||selected.isNewShape())return;drag={edge:edge,selected:selected};e.preventDefault();e.stopPropagation();};
 this.edgeMove=function(e){if(!drag)return;var r=container.getBoundingClientRect();if(!r.width||!r.height)return;var b=bfBox(drag.selected.shape),x=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y=Math.max(0,Math.min(1,(e.clientY-r.top)/r.height)),gapX=2/r.width,gapY=2/r.height;
  if(drag.edge==='left')b[0]=Math.min(x,b[2]-gapX);if(drag.edge==='right')b[2]=Math.max(x,b[0]+gapX);if(drag.edge==='top')b[1]=Math.min(y,b[3]-gapY);if(drag.edge==='bottom')b[3]=Math.max(y,b[1]+gapY);
  var s=drag.selected,p=s.shape.data.p1,q=s.shape.data.p2;p.x=b[0];p.y=b[1];q.x=b[2];q.y=b[3];s._el.rect.p1=p;s._el.rect.p2=q;s._el.p1.point=p;s._el.p2.point=q;s.rerender();s.emitUpdate();self.refresh();e.preventDefault();e.stopPropagation();
 };
 this.edgeUp=function(){drag=null;};
 this.drawEvent=function(e){var r=container.getBoundingClientRect();return {clientX:Math.max(r.left,Math.min(r.right||r.left+r.width,e.clientX)),clientY:Math.max(r.top,Math.min(r.bottom||r.top+r.height,e.clientY)),stopPropagation:function(){}};};
 this.drawDown=function(e){
  suppressClick=false;
  if(!self.active()||panMode||e.button!==0||e.target.closest('.bf-edge-overlay'))return;
  var current=editor._activeShapeEditor,isNew=current&&current.isNewShape();
  if(!isNew&&(!container.contains(e.target)||self.shapeAt(e)))return;
  if(current&&!isNew){self.clear();e.preventDefault();e.stopImmediatePropagation();return;}
  if(!isNew){self.add();current=editor._activeShapeEditor;}
  if(!current||!current.isNewShape())return;
  if(!draw||draw.editor!==current)draw={editor:current,x:e.clientX,y:e.clientY,second:false};else draw.second=!!current._isAnchorPointSet;
  draw.pressed=true;current._onMouseDown(self.drawEvent(e));e.preventDefault();e.stopImmediatePropagation();self.refresh();
 };
 this.drawMove=function(e){if(!draw||!self.active()||editor._activeShapeEditor!==draw.editor)return;draw.editor._onMouseMove(self.drawEvent(e));e.preventDefault();e.stopImmediatePropagation();};
 this.drawUp=function(e){if(!draw||!draw.pressed||editor._activeShapeEditor!==draw.editor)return;var moved=Math.hypot(e.clientX-draw.x,e.clientY-draw.y)>4;draw.pressed=false;if(moved&&(draw.second||e.type==='mouseup')){var current=draw.editor;draw=null;current._onMouseUp(self.drawEvent(e));suppressClick=true;}e.preventDefault();e.stopImmediatePropagation();self.refresh();};
 this.mouseDown=function(e){down={x:e.clientX,y:e.clientY};};
 this.click=function(e){if(suppressClick){suppressClick=false;e.preventDefault();e.stopImmediatePropagation();return;}if(panMode){e.stopImmediatePropagation();return;}if(!self.active()||e.target.closest('.bf-edge-overlay'))return;var selected=editor._activeShapeEditor;if(selected&&selected.isNewShape()){e.stopImmediatePropagation();return;}
  var shape=self.shapeAt(e);
  if(shape){e.stopImmediatePropagation();if(down&&Math.hypot(e.clientX-down.x,e.clientY-down.y)>4)return;if(selected===shape&&!e.target.closest('.ia-element-point,.ia-element-point-underlay'))self.clear();else{if(selected!==shape)editor._onShapeActivate(shape);shape._el.rect.activate();self.refresh();}}
  else if(e.target===viewport||container.contains(e.target)){e.stopImmediatePropagation();self.clear();}
 };
 this.enter=function(){
  var selected=editor._activeShapeEditor;
  if(task._correctionNotice && !panMode && !draw && !drag && (!selected || !selected.isNewShape())){
   if(task._correctionNotice.advanceFrame())return;
  }
  if(selected||panMode||draw||drag)self.finish();
  else task.submitOrCompare();
 };
 this.key=function(e){if(e.target.closest && e.target.closest('.bf-instructions,.bf-film-open'))return;if(!self.active()||e.ctrlKey||e.metaKey||e.altKey||e.target.isContentEditable||/TEXTAREA|SELECT/.test(e.target.tagName)||e.target.tagName==='INPUT'&&e.target.type!=='checkbox')return;var code=e.code,key=e.key.toLowerCase(),used=true;if(code==='KeyN'||code==='KeyB'||!code&&(key==='n'||key==='b')){if(!e.repeat)self.add();}else if(code==='KeyV'||!code&&key==='v'){if(!e.repeat)self.pan();}else if(code==='KeyD'||!code&&key==='d'||e.key==='Delete'||e.key==='Backspace'){if(!e.repeat)self.remove();}else if(e.key==='Enter'){if(!e.repeat)self.enter();}else if(e.key==='Escape')self.clear();else if(code==='KeyR'||!code&&key==='r'){if(!e.repeat){self.finish();root.querySelector('.bf-reviewed').click();}}else used=false;if(used){e.preventDefault();e.stopImmediatePropagation();}};
 add.onclick=this.add;remove.onclick=this.remove;cancel.onclick=this.clear;pan.onclick=this.pan;
 overlay.addEventListener('pointerdown',this.edgeDown);document.addEventListener('pointermove',this.edgeMove,true);document.addEventListener('pointerup',this.edgeUp,true);document.addEventListener('pointercancel',this.edgeUp,true);viewport.addEventListener('mousedown',this.drawDown,true);document.addEventListener('mousemove',this.drawMove,true);document.addEventListener('mouseup',this.drawUp,true);viewport.addEventListener('mousedown',this.mouseDown,true);viewport.addEventListener('click',this.click,true);document.addEventListener('keydown',this.key,true);
 ['shape:editor:activated','shapes:update','shape:finish','shape:cancel'].forEach(function(e){editor.on(e,self.refresh);});editor.on('shape:finish',this.shapeFinish);this.refresh();
 this.destroy=function(){editor.removeListener('shape:finish',self.shapeFinish);overlay.remove();document.removeEventListener('pointermove',self.edgeMove,true);document.removeEventListener('pointerup',self.edgeUp,true);document.removeEventListener('pointercancel',self.edgeUp,true);viewport.removeEventListener('mousedown',self.drawDown,true);document.removeEventListener('mousemove',self.drawMove,true);document.removeEventListener('mouseup',self.drawUp,true);viewport.removeEventListener('mousedown',self.mouseDown,true);viewport.removeEventListener('click',self.click,true);document.removeEventListener('keydown',self.key,true);['shape:editor:activated','shapes:update','shape:finish','shape:cancel'].forEach(function(e){editor.removeListener(e,self.refresh);});};
}
// Load the native editor image once. Its SDK rebuilds all shape handles on a
// second image load, so the full-resolution layer goes underneath the same SVG.
function bfAnnotationPhoto(root, img, input) {
 var original = input.display_image_url || input.image_url || '';
 var small = original.replace(/^(https:\/\/inaturalist-open-data\.s3\.amazonaws\.com\/photos\/\d+\/)original\.jpg$/, '$1large.jpg');
 var status = root.querySelector('.bf-photo-loading'), label = status.querySelector('span'), retry = status.querySelector('button');
 var source = '', detail = null, detailFailed = false, zoomScale = 1;
 var photo = {ready:false};
 function load(url) {
  source = url;
  status.hidden = false;
  label.textContent = 'Загружаем фото…';
  retry.hidden = true;
  img.fetchPriority = 'high';
  img.src = url;
 }
 function loaded() {
  photo.ready = true;
  status.hidden = true;
 }
 function failed() {
  if (!source || img.complete && img.naturalWidth) return;
  if (source !== original) { load(original); return; }
  label.textContent = 'Фото не загрузилось.';
  retry.hidden = false;
 }
 photo.show = function() {
  if (!original) { label.textContent = 'В задании отсутствует ссылка на фотографию.'; return; }
  if (!source) load(small);
 };
 photo.zoom = function(scale) {
  zoomScale = scale;
  if (scale <= 1) {
   if (detailFailed) { detailFailed = false; status.hidden = true; }
   return;
  }
  if (!photo.ready || source === original || detail || detailFailed) return;
  detail = root.ownerDocument.createElement('img');
  detail.className = 'bf-detail-photo';
  detail.alt = '';
  detail.hidden = true;
  detail.onload = function() { detail.hidden = false; status.hidden = true; };
  detail.onerror = function() {
   detail.remove(); detail = null;
   if (zoomScale <= 1) return;
   detailFailed = true;
   label.textContent = 'Оригинал не загрузился. Пока показана уменьшенная копия.';
   retry.hidden = false; status.hidden = false;
  };
  img.after(detail);
  detail.src = original;
 };
 img.addEventListener('load',loaded);
 img.addEventListener('error',failed);
 retry.onclick = function() {
  if (detailFailed) { detailFailed = false; status.hidden = true; photo.zoom(zoomScale); }
  else load(original);
 };
 photo.destroy = function() {
  img.removeEventListener('load',loaded);
  img.removeEventListener('error',failed);
  retry.onclick = null;
  if (detail) { detail.onload = detail.onerror = null; detail.remove(); }
 };
 return photo;
}

// The task package includes the small MP4 so it can play inside a closed pool.
function bfTutorial(root) {
 var buttons=root.querySelectorAll('.bf-film-open'), dialog=root.querySelector('.bf-film'), opener;
 var video=dialog.querySelector('video'), close=dialog.querySelector('.bf-film-close');
 var win=root.ownerDocument.defaultView;
 function keys(event) {
  if(event.key==='Escape'){event.preventDefault();dialog.close();}
  event.stopPropagation();
 }
 function cleanup() {
  win.removeEventListener('keydown',keys,true);
  if(video.hasAttribute('src'))video.pause();
 }
 function show(event) {
  if(dialog.open)return;
  opener=event.currentTarget;
  if(!video.hasAttribute('src'))video.src='data:video/mp4;base64,__BF_GUIDE_MP4__';
  dialog.showModal();
  video.tabIndex=0;video.focus();
  win.addEventListener('keydown',keys,true);
  video.play().catch(function(){/* Native controls also allow playback. */});
 }
 buttons.forEach(function(button){button.onclick=show;});
 close.onclick=function(){dialog.close();};
 dialog.onclose=function(){cleanup();if(opener)opener.focus();};
 video.onerror=function(){dialog.querySelector('.bf-film-error').hidden=false;};
 return function(){cleanup();if(dialog.open)dialog.close();};
}
exports.Task=inherit(TolokaHandlebarsTask,{
 onRender:function(){
  var self=this,root=this.getDOMElement(),input=this.getTask().input_values,out=this.getSolution().output_values||{};
  this._restoredReview=out.reviewed===true;
  bfPrepareLayout(root,false);
  this._closeTutorial=bfTutorial(root);
  if(!Array.isArray(out.result))this.setSolutionOutputValue('result',JSON.parse(JSON.stringify(input.editable_annotations||[])));
  if(typeof out.reviewed!=='boolean')this.setSolutionOutputValue('reviewed',false);
  this.setSolutionOutputValue('practice_passed',false);
  var reviewed=root.querySelector('.bf-reviewed'),empty=root.querySelector('.bf-empty-check');reviewed.checked=!!out.reviewed;empty.checked=!!out.empty_confirmed;
  var prompt=root.querySelector('.bf-review-prompt');prompt.id='bf-review-prompt-'+this.getTask().id;
  reviewed.onchange=function(){self.setSolutionOutputValue('reviewed',reviewed.checked);self.showReviewError(false);root.dispatchEvent(new CustomEvent('bf-progress',{bubbles:true}));};
  empty.onchange=function(){
   self.setSolutionOutputValue('empty_confirmed',empty.checked&&!empty.disabled);
   if(notice){
    reviewed.checked=false;reviewed.onchange();
    notice.check(self.getSolution().output_values.result);
   }
  };
  var editor=this.getField('result').getEditor();this._editor=editor;
  var notice=this._correctionNotice=bfCorrectionNotice(root,input,editor,!!this.getWorkspaceOptions().isReadOnly,function(shape){if(shape)self._controls.select(shape);else self._controls.clear();});
  this.syncEmpty=function(){var hasBoxes=(self.getSolution().output_values.result||[]).length>0;empty.disabled=hasBoxes||input.practice||self.getWorkspaceOptions().isReadOnly;root.querySelector('.bf-empty').classList.toggle('is-disabled',!!hasBoxes);if(hasBoxes||input.practice){empty.checked=false;self.setSolutionOutputValue('empty_confirmed',false);}};
  this._shapeUpdate=function(shapes){self._practiceCompared=false;self.showReviewError(false);self.setSolutionOutputValue('result',shapes||[]);self.setSolutionOutputValue('reviewed',false);reviewed.checked=false;self.syncEmpty();if(notice)notice.check(shapes);if(input.practice){self._practicePass=false;self.setSolutionOutputValue('practice_passed',false);root.querySelector('.bf-feedback').textContent='Рамка изменена. Сравните её ещё раз.';}root.dispatchEvent(new CustomEvent('bf-progress',{bubbles:true}));};
  editor.on('shapes:update',this._shapeUpdate);this.syncEmpty();
  if(notice)notice.check(this.getSolution().output_values.result);
  if(input.practice){root.querySelector('.bf-practice-threshold').textContent='Нужно совпадение ≥ '+Math.round((input.iou_threshold||0.8)*100)+'%';this.setSolutionOutputValue('practice_passed',false);root.querySelector('.bf-check').onclick=function(){self.checkPractice();};}
  var host=root.querySelector('.bf-editor'),container=host.querySelector('.image-annotation-editor__canvas-container'),viewport=host.querySelector('.image-annotation-editor__annotation-layer'),img=host.querySelector('.image-annotation-editor__image');
  this._photo=bfAnnotationPhoto(root,img,input);
  this._photoFrame=root.ownerDocument.defaultView.requestAnimationFrame(function(){if(root.getClientRects().length)self._photo.show();});
  var fitPercent=100;this._zoom=new BFZoom(root,viewport,{nativePan:true,wheelPan:true,fit:function(){if(img&&img.naturalWidth&&viewport.clientWidth)fitPercent=Math.min(100,100*viewport.clientHeight/(viewport.clientWidth*img.naturalHeight/img.naturalWidth));},set:function(z){viewport.style.textAlign=fitPercent*z<=100?'center':'left';editor.zoom=fitPercent*z;self._photo.zoom(z);if(self._controls)self._controls.refresh();}});
  this._controls=new BFBBoxControls(this,editor,root,container,viewport);
  this._screen=new BFScreenFit(root,viewport,function(){if(self._zoom.scale===1)self._zoom.fit();else self._zoom.set(self._zoom.scale);});
  this._imageLoad=function(){self._zoom.adapter.fit();self._zoom.set(self._zoom.scale);self._screen.schedule();};if(img)img.addEventListener('load',this._imageLoad);
  this._guide=bfLayer(container,'bf-guide-overlay');
  if(input.fixed_boxes&&input.fixed_boxes.length){var svg=bfLayer(container,'bf-fixed-overlay');svg.style.pointerEvents='none';input.fixed_boxes.forEach(function(b){var halo=bfRect(svg,b.bbox||b,'#ffffff');halo.classList.add('bf-fixed-halo');halo.setAttribute('stroke-width','13');halo.setAttribute('stroke-dasharray','13 8');halo.style.pointerEvents='none';var r=bfRect(svg,b.bbox||b,'#d92336');r.classList.add('bf-fixed-box');r.setAttribute('stroke-width','11');r.setAttribute('stroke-dasharray','13 8');r.setAttribute('fill','none');r.style.pointerEvents='none';var title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent='Уже проверено — эту рамку нельзя двигать или изменять';r.appendChild(title);});}
  if(this.getWorkspaceOptions().isReadOnly)root.querySelectorAll('input,button').forEach(function(el){el.disabled=true;});
 },
 checkPractice:function(){
  var root=this.getDOMElement(),input=this.getTask().input_values,a=this.getSolution().output_values.result||[],ref=input.reference_boxes;
  this._guide.textContent='';this._practicePass=false;this._practiceCompared=false;this.setSolutionOutputValue('practice_passed',false);
  if(!Array.isArray(ref)||ref.length!==1||!Array.isArray(ref[0])||ref[0].length!==4){root.querySelector('.bf-reference').hidden=true;root.querySelector('.bf-feedback').textContent='Учебный ориентир не загрузился. Обновите задание; оценка совпадения пока недоступна.';this._screen.schedule();return;}
  var threshold=input.iou_threshold||0.8;
  var b=a.length===1?bfBox(a[0]):null,score=b?bfIoU(b,ref[0]):0;this._practicePass=score>=threshold&&a.length===1;this.setSolutionOutputValue('practice_passed',this._practicePass);this._practiceCompared=true;
  root.querySelector('.bf-reference').hidden=false;var halo=bfRect(this._guide,ref[0],'#fff');halo.classList.add('bf-guide-halo');halo.setAttribute('stroke-dasharray','10 5');var outline=bfRect(this._guide,ref[0],'#1670ec');outline.classList.add('bf-guide-box');outline.setAttribute('stroke-dasharray','10 5');var title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent='Учебный ориентир';outline.appendChild(title);
  var fixed=input.fixed_boxes||[];
  var copiedFixed=!this._practicePass&&fixed.length&&a.some(function(shape){
   var coords=bfBox(shape);
   return coords&&bfIoU(coords,ref[0])<threshold&&fixed.some(function(frame){return bfIoU(coords,frame.bbox||frame)>=threshold;});
  });
  var feedback=root.querySelector('.bf-feedback');
  if(copiedFixed){
   feedback.textContent='Оранжевая рамка повторяет красную. Эта бабочка уже размечена. Удалите оранжевую копию клавишей Del. Оставьте одну оранжевую рамку вокруг бабочки, отмеченной синим ориентиром.';
  }else{
   feedback.textContent='Совпадение: '+Math.round(score*100)+'%. '+(this._practicePass?'Пример пройден. Подтвердите просмотр (R), если ещё не отметили, и нажмите Enter для отправки.':'Нужно ≥ '+Math.round(threshold*100)+'%. Исправьте рамку по синему ориентиру.');
  }
  this._screen.schedule();
 },
 showReviewError:function(show,focus){
  var root=this.getDOMElement(),group=root.querySelector('.bf-review-confirmation'),checkbox=root.querySelector('.bf-reviewed'),prompt=root.querySelector('.bf-review-prompt');
  group.classList.toggle('is-invalid',!!show);prompt.hidden=!show;
  if(show){checkbox.setAttribute('aria-invalid','true');checkbox.setAttribute('aria-describedby',prompt.id);if(focus){checkbox.focus({preventScroll:true});if(group.scrollIntoView)group.scrollIntoView({block:'nearest',inline:'nearest'});}}
  else{checkbox.removeAttribute('aria-invalid');checkbox.removeAttribute('aria-describedby');}
 },
 submitOrCompare:function(){
  var input=this.getTask().input_values,out=this.getSolution().output_values;
  if(input.practice){
   if(!Array.isArray(out.result)||!out.result.length||out.result.some(function(a){return !bfBox(a);})||!out.reviewed){var error=this.validate();if(error)this.onValidationFail(error);return;}
   if(!this._practiceCompared||!this._practicePass){this.checkPractice();return;}
  }
  if(this._correctionNotice){
   var issue=this.validate();
   if(issue){this.onValidationFail(issue);return;}
   if(this._advanceCorrection){this._advanceCorrection();return;}
  }
  if(this.getAssignment)this.getAssignment().submit();
 },
 validate:function(solution){
  var answer=solution||this.getSolution(),out=answer.output_values||{},input=this.getTask().input_values,message='',field='result';
  var correctionError=this._correctionNotice && Array.isArray(out.result) ? this._correctionNotice.check(out.result,out.empty_confirmed===true) : '';
  if(this._photo && !this._photo.ready && !(this._restoredReview && out.reviewed))message='Дождитесь загрузки фотографии перед отправкой.';
  else if(!Array.isArray(out.result)||out.result.some(function(a){return !bfBox(a);}))message='Разрешены только непустые прямоугольники в пределах фотографии.';
  else if(correctionError)message=correctionError;
  else if(out.result.length&&out.empty_confirmed)message='Есть редактируемые рамки. Снимите отметку «Добавлять рамки не нужно».';
  else if(!out.result.length&&!out.empty_confirmed)message=input.practice?'Добавьте одну рамку вокруг бабочки без фиксированной рамки.':'Добавьте рамку или подтвердите, что добавлять рамки не нужно.';
  else if(!out.reviewed){message='Подтвердите здесь: я просмотрел(а) всё фото.';field='reviewed';}
  else if(input.practice&&(!Array.isArray(input.reference_boxes)||input.reference_boxes.length!==1))message='Учебный ориентир не загрузился. Обновите задание; проверка временно недоступна.';
  else if(input.practice){var b=out.result.length===1?bfBox(out.result[0]):null;var threshold=input.iou_threshold||0.8,pass=!!b&&bfIoU(b,input.reference_boxes[0])>=threshold;this.setSolutionOutputValue('practice_passed',!!pass);out.practice_passed=!!pass;if(!pass)message='Исправьте учебную рамку: нужно совпадение не менее '+Math.round(threshold*100)+'%.';}
  var errors=TolokaHandlebarsTask.prototype.validate.call(this,answer),el=this.getDOMElement().querySelector('.bf-error');
  this.showReviewError(!!message&&field==='reviewed');el.hidden=!message||field==='reviewed';el.textContent=field==='reviewed'?'':message;
  if(message){errors=errors||{task_id:this.getTask().id,errors:{}};errors.errors=errors.errors||{};errors.errors[field]={code:'CUSTOM',message:message};}if(this._screen)this._screen.schedule();return errors;
 },
 onValidationFail:function(error){
  var nativeErrors={};Object.keys((error||{}).errors||{}).forEach(function(k){if(error.errors[k].code!=='CUSTOM')nativeErrors[k]=error.errors[k];});if(Object.keys(nativeErrors).length&&TolokaHandlebarsTask.prototype.onValidationFail)TolokaHandlebarsTask.prototype.onValidationFail.call(this,{task_id:this.getTask().id,errors:nativeErrors});
  var entries=(error||{}).errors||{},el=this.getDOMElement().querySelector('.bf-error');this.showReviewError(!!entries.reviewed,!!entries.reviewed);
  el.textContent=Object.keys(entries).filter(function(k){return k!=='reviewed';}).map(function(k){return entries[k].message||'Проверьте заполнение фотографии.';}).join(' ');el.hidden=!el.textContent;if(this._screen)this._screen.schedule();
 },
 onDestroy:function(){this.getDOMElement().ownerDocument.defaultView.cancelAnimationFrame(this._photoFrame);if(this._photo)this._photo.destroy();if(this._correctionNotice)this._correctionNotice.destroy();if(this._closeTutorial)this._closeTutorial();if(this._editor&&this._shapeUpdate)this._editor.removeListener('shapes:update',this._shapeUpdate);if(this._controls)this._controls.destroy();if(this._screen)this._screen.destroy();if(this._zoom)this._zoom.destroy();var img=this.getDOMElement().querySelector('.image-annotation-editor__image');if(img&&this._imageLoad)img.removeEventListener('load',this._imageLoad);}
});
exports.TaskSuite=inherit(TolokaTaskSuite,{
 onRender:function(){var self=this,root=this.getDOMElement();bfPrepareLayout(root,true);this._unbindFullscreen=bfBindFullscreen(this);this._tasks=this.getTasks();this._index=0;if(this._tasks.length<2){if(this._tasks[0]&&this._tasks[0]._photo)this._tasks[0]._photo.show();return;}this._nav=document.createElement('nav');this._nav.className='bf-bbox-pager';this._nav.innerHTML='<button type="button" class="bf-prev">← Назад</button><strong class="bf-progress"></strong><div class="bf-steps"></div><button type="button" class="bf-next">Далее →</button>';root.insertBefore(this._nav,root.firstChild);this._tasks.forEach(function(t,i){if(t._correctionNotice && i < self._tasks.length - 1)t._advanceCorrection=function(){self.requestShow(i+1);};var b=document.createElement('button');b.type='button';b.textContent=i+1;b.setAttribute('aria-label','Фото '+(i+1));b.onclick=function(){self.requestShow(i);};self._nav.querySelector('.bf-steps').appendChild(b);});this._nav.querySelector('.bf-prev').onclick=function(){self.show(self._index-1);};this._nav.querySelector('.bf-next').onclick=function(){self.requestShow(self._index+1);};this._progress=function(){self.refresh();};root.addEventListener('bf-progress',this._progress);this._key=function(e){if(e.ctrlKey||e.metaKey||e.altKey||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();self.requestShow(self._index+(e.key==='ArrowLeft'?-1:1));}};document.addEventListener('keydown',this._key);this.show(0);},
 refresh:function(){if(!this._nav)return;var self=this,count=0;this._tasks.forEach(function(t,i){var done=!!t.getSolution().output_values.reviewed;if(done)count++;var b=self._nav.querySelectorAll('.bf-steps button')[i];b.classList.toggle('active',i===self._index);b.classList.toggle('answered',done);b.setAttribute('aria-current',i===self._index?'step':'false');});this._nav.querySelector('.bf-progress').textContent='Фото '+(this._index+1)+' / '+this._tasks.length+' · просмотрено '+count;this._nav.querySelector('.bf-prev').disabled=this._index===0;this._nav.querySelector('.bf-next').disabled=this._index===this._tasks.length-1;},
 requestShow:function(index){
  for(var i=this._index;i<Math.min(index,this._tasks.length);i++){
   var task=this._tasks[i];
   if(task._correctionNotice){
    var error=task.validate();
    if(error){if(i!==this._index)this.show(i);task.onValidationFail(error);return false;}
   }
  }
  this.show(index);return true;
 },
 show:function(index){if(!this._tasks)return;this._index=Math.max(0,Math.min(index,this._tasks.length-1));var self=this;this._tasks.forEach(function(t,i){if(i!==self._index&&t._controls)t._controls.clear();t.showReviewError(false);var error=t.getDOMElement().querySelector('.bf-error');error.hidden=true;error.textContent='';t.getDOMElement().style.display=i===self._index?'block':'none';});this.refresh();var t=this._tasks[this._index];if(t&&t._photo)t._photo.show();if(t&&t._controls)t._controls.refresh();if(t&&t._screen)t._screen.schedule();},
 focusTask:function(i){if(this._nav&&!this.requestShow(i))return;TolokaTaskSuite.prototype.focusTask.call(this,i);},
 onValidationFail:function(errors){if(TolokaTaskSuite.prototype.onValidationFail)TolokaTaskSuite.prototype.onValidationFail.call(this,errors);var first=(errors||[]).find(function(e){return !!e;});if(first){var i=this._tasks.findIndex(function(t){return t.getTask().id===first.task_id;});if(i>=0){this.show(i);this._tasks[i].onValidationFail(first);}}},
 onDestroy:function(){if(this._unbindFullscreen)this._unbindFullscreen();if(this._key)document.removeEventListener('keydown',this._key);if(this._progress)this.getDOMElement().removeEventListener('bf-progress',this._progress);}
});
