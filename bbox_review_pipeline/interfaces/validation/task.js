function inherit(Parent,methods){function Child(o){Parent.call(this,o);}Child.prototype=Object.create(Parent.prototype);Object.keys(methods).forEach(function(k){Child.prototype[k]=methods[k];});Child.prototype.constructor=Child;return Child;}
function rect(svg,b,color,width,fill){var r=document.createElementNS('http://www.w3.org/2000/svg','rect');['x','y','width','height'].forEach(function(k,i){r.setAttribute(k,[b[0]*1000,b[1]*1000,(b[2]-b[0])*1000,(b[3]-b[1])*1000][i]);});r.setAttribute('stroke',color);r.setAttribute('stroke-width',width);r.setAttribute('vector-effect','non-scaling-stroke');r.setAttribute('fill',fill||'none');svg.appendChild(r);return r;}
function bfReviewAnswered(out){
 return !!out.answer&&(out.answer!=='duplicate'||out.duplicate_reason==='fixed'||out.duplicate_reason==='earlier');
}
function bfValidReviewBox(box){
 return Array.isArray(box)&&box.length===4&&box.every(function(n){return Number.isFinite(n)&&n>=0&&n<=1;})&&box[0]<box[2]&&box[1]<box[3];
}
exports.Task=inherit(TolokaHandlebarsTask,{
 getTemplateData:function(){
  var input=this.getTask().input_values;
  // The requester's generated example has a stock photo, field-name placeholders
  // and no JSON coordinates. Keep custom preview inputs and issued work intact.
  if(!/^https:\/\/yastatic-net\.ru\/s3\/yang\/p\/requester\//.test(input.image_url)||
     String(input.focus_box_id).indexOf('focus_box_id')<0||bfValidReviewBox(input.focus_bbox))return input;
  var assignment=this.getAssignment&&this.getAssignment();
  if(assignment&&typeof assignment.getId==='function'&&assignment.getId())return input;
  var bbox=[0.2263736,0.1802198,0.7582417,0.8329671];
  return {image_url:'https://inaturalist-open-data.s3.amazonaws.com/photos/760692486/large.jpg',
   review_type:'box',focus_box_id:'example',focus_bbox:bbox,box_index:0,box_count:1,
   context_boxes:[{box_id:'example',bbox:bbox,fixed:false}]};
 },
 onRender:function(){
  var self=this,r=this.getDOMElement(),v=this.getTemplateData(),coverage=v.review_type==='coverage';
  bfPrepareLayout(r,false);this._canRepeat=false;
  this._choices=coverage?[['missing_no','Все бабочки выделены'],['missing_yes','Есть невыделенные бабочки без рамки']]:[
   ['box_correct','Верно — бабочка выделена целиком'],
   ['bad_geometry','Неверно — обрезана бабочка или много лишнего фона'],
   ['extra_box','Неверно — в рамке нет бабочки'],
   ['duplicate','Повтор — эта бабочка уже в красной рамке или вы уже проверили её в другой рамке на этом фото']
  ];
  r.querySelector('.bf-question').textContent=coverage?'Есть ли на фото невыделенные бабочки?':'Правильно ли выделена бабочка в оранжевой рамке?';
  r.querySelector('.bf-hint').textContent=coverage?'Осмотрите всё фото и найдите бабочек, вокруг которых вообще нет прямоугольника.':'Посмотрите на каждую сторону. Если её можно заметно сдвинуть внутрь, не задев бабочку, выберите 2. Небольшой отступ допустим.';
  var svg=r.querySelector('svg');
  var context=Array.isArray(v.context_boxes)?v.context_boxes:[];
  this._invalidFrames=(!coverage&&!bfValidReviewBox(v.focus_bbox))||
   (v.context_boxes!=null&&!Array.isArray(v.context_boxes))||
   context.some(function(b){return !b||!bfValidReviewBox(b.bbox);});
  if(this._invalidFrames){
   context=[];
   var warning=r.querySelector('.bf-task-feedback');
   warning.textContent='Не удалось прочитать координаты рамок. В предпросмотре откройте «Изменить входные данные» и укажите координаты. В рабочем задании пропустите эту страницу.';
   warning.hidden=false;
  }
  var fixed=context.filter(function(b){return b.fixed;});
  this._hasFixedReference=!coverage&&fixed.length>0;
  fixed.forEach(function(b){rect(svg,b.bbox,'#d92336',12).classList.add('bf-fixed-reference');});
  var other=context.filter(function(b){return !b.fixed&&(coverage||b.box_id!==v.focus_box_id);});
  other.forEach(function(b){rect(svg,b.bbox,'#2475d4',6).classList.add('bf-context-frame');});
  if(!coverage&&!this._invalidFrames)rect(svg,v.focus_bbox,'#ff8b26',4,'rgba(255,139,38,0.07)').classList.add('bf-focus-frame');
  var isolate=r.querySelector('.bf-isolate-fixed');
  if(!coverage&&(fixed.length||other.length)){
   isolate.hidden=false;
   isolate.onclick=function(){
    var hidden=svg.classList.toggle('bf-hide-focus');
    isolate.textContent=hidden?'Показать оранжевую':'Скрыть оранжевую';
   };
  }
  this._choices.forEach(function(c,i){var b=document.createElement('button');b.type='button';b.dataset.answer=c[0];b.innerHTML='<kbd>'+(i+1)+'</kbd>';b.appendChild(document.createTextNode(c[1]));b.onclick=function(){self.choose(i);};r.querySelector('.bf-answers').appendChild(b);});
  r.querySelector('.bf-tag').textContent=(coverage?'1–2':'1–4')+' — выбрать ответ · Enter — далее';
  r.querySelector('.bf-question-tag').textContent=coverage?'Проверка всего фото':'Рамка '+((v.box_index||0)+1)+' из '+(v.box_count||1);
  var caption=r.querySelector('.bf-focus-caption');
  var legend=coverage?[]:['Оранжевая — текущая'];
  if(fixed.length)legend.push('красный пунктир — зафиксированная');
  if(other.length)legend.push('синие — остальные');
  caption.textContent=legend.length?legend.join(' · '):'Осмотрите всё фото';
  if(coverage)r.querySelector('.bf-review-guide').innerHTML='<h3>Ищите бабочек без рамки</h3><p>Если вокруг каждой есть рамка, выберите «Все бабочки выделены». Если нашли хотя бы одну без рамки — «Есть невыделенные бабочки без рамки».</p><p>Если бабочку обрезала сторона рамки, вернитесь к вопросу об этой рамке и выберите ответ 2.</p>';
  if(v.training){r.querySelector('.bf-review').classList.add('is-training');r.querySelector('.bf-review-heading h2').textContent='Обучение: проверка разметки';}
  if(v.training&&v.expected_answer&&v.training_hint){
   this._lessonChoice=Object.assign({},this.getSolution().output_values);
   r.querySelector('.bf-hint').textContent='Выберите ответ и нажмите Enter, чтобы проверить себя.';
   r.querySelector('.bf-validation-help p:last-child').textContent='Enter проверяет учебный ответ. При ошибке прочитайте подсказку и исправьте выбор. После верного ответа нажмите Enter ещё раз для перехода.';
  }
  this._reasonGroup=r.querySelector('.bf-repeat-reason');
  this._reasonButtons=this._reasonGroup.querySelectorAll('button[data-reason]');
  this._reasonButtons.forEach(function(button){
   button.onclick=function(){
    if(self.reviewChoice().answer==='duplicate')self.setReviewValue('duplicate_reason',button.dataset.reason);
   };
  });
  this.updateRepeatAccess(false);this.refreshAnswer();
  var img=r.querySelector('img'),vp=r.querySelector('.bf-viewport'),photo=r.querySelector('.bf-photo');
  this._zoom=new BFZoom(r,vp,{set:function(scale){photo.style.setProperty('--bf-zoom',scale);}});
  this._imageFailed=false;
  img.onerror=function(){self._imageFailed=true;r.querySelector('.bf-image-error').hidden=false;};
  img.onload=function(){
   photo.style.setProperty('--bf-aspect',img.naturalWidth/img.naturalHeight);
   self._imageFailed=false;r.querySelector('.bf-image-error').hidden=true;
  };
  if(img.complete){if(img.naturalWidth)img.onload();else img.onerror();}
  if(this._invalidFrames||this.getWorkspaceOptions().isReadOnly)r.querySelectorAll('.bf-answers button').forEach(function(b){b.disabled=true;});
 },
 updateRepeatAccess:function(ready){
  var v=this.getTemplateData(),b=this.getDOMElement().querySelector('[data-answer="duplicate"]');
  this._hasEarlierReference=!!ready&&(v.box_index||0)>0;
  this._canRepeat=this._hasFixedReference||this._hasEarlierReference;
  var readOnly=this._invalidFrames||this.getWorkspaceOptions().isReadOnly;
  this._reasonButtons[0].disabled=readOnly||!this._hasFixedReference;
  this._reasonButtons[1].disabled=readOnly||!this._hasEarlierReference;
  if(!b)return;
  b.disabled=!this._canRepeat||readOnly;
  var note=this.getDOMElement().querySelector('.bf-repeat-access');
  note.hidden=this._canRepeat;
  note.textContent=(v.box_index||0)>0?'Чтобы отметить повтор, сначала оцените предыдущие рамки этого фото.':
   v.box_count===1?'На фото одна рамка. Повтор можно отметить, когда ту же бабочку уже выделяет другая рамка.':'Это первая рамка на фото. Если другая рамка выделит ту же бабочку, отметьте повтор у второй.';
  b.title=this._canRepeat?'Сравните с красным пунктиром или ранее проверенной рамкой этой бабочки.':note.textContent;
 },
 reviewChoice:function(){return this._lessonChoice||this.getSolution().output_values;},
 choose:function(i){
  var choice=this._choices[i];
  if(choice&&(choice[0]!=='duplicate'||this._canRepeat))this.setReviewValue('answer',choice[0]);
 },
 setReviewValue:function(field,value){
  if(this._invalidFrames||this._imageFailed||this.getWorkspaceOptions().isReadOnly)return;
  var root=this.getDOMElement();
  if(this._lessonChoice){
   if(this._lessonChoice[field]===value){bfFocusTask(root);return;}
   this._lessonChoice[field]=value;
   if(field==='answer'&&value!=='duplicate')delete this._lessonChoice.duplicate_reason;
   this._lessonPassed=false;
   root.querySelector('.bf-lesson-feedback').hidden=true;
  }else{
   if(field==='answer'&&value!=='duplicate'&&this.getSolution().output_values.duplicate_reason)this.setSolutionOutputValue('duplicate_reason',undefined);
   this.setSolutionOutputValue(field,value);
  }
  this._reasonGroup.removeAttribute('aria-invalid');
  root.querySelector('.bf-task-feedback').hidden=true;
  this.refreshAnswer();bfFocusTask(root);
  root.dispatchEvent(new CustomEvent('bf-answer',{bubbles:true,detail:{task:this}}));
 },
 onValidationFail:function(error){
  if(TolokaHandlebarsTask.prototype.onValidationFail)TolokaHandlebarsTask.prototype.onValidationFail.call(this,error);
  var errors=(error||{}).errors||{},v=this.getTemplateData();
  if(errors.duplicate_reason)this._reasonGroup.setAttribute('aria-invalid','true');
  var messages=Object.keys(errors).map(function(k){return errors[k].message||'Проверьте выбранный ответ.';});
  var el=this.getDOMElement().querySelector('.bf-task-feedback');
  if(this._lessonPassed&&(errors.__TASK__||messages.indexOf(v.training_hint)>=0)){
   // Native training has now graded the original submission. Its retry uses the correction.
   this._lessonRetry=true;this.saveLessonChoice();
   messages=['Ответ уже исправлен. Нажмите «Отправить исправления».'];
  }
  el.textContent=messages.join(' ');el.hidden=!messages.length;
 },
 saveLessonChoice:function(){
  this.setSolutionOutputValue('answer',this._lessonChoice.answer);
  this.setSolutionOutputValue('duplicate_reason',this._lessonChoice.duplicate_reason);
 },
 checkLesson:function(){
  var choice=this._lessonChoice,v=this.getTemplateData(),error=this.reviewError(choice);
  if(error){this.onValidationFail(error);return;}
  if(!bfReviewAnswered(this.getSolution().output_values)||this._lessonRetry)this.saveLessonChoice();
  var answer=choice.answer==='duplicate'?choice.answer+':'+choice.duplicate_reason:choice.answer;
  this._lessonPassed=answer===v.expected_answer;
  var root=this.getDOMElement(),el=root.querySelector('.bf-lesson-feedback');
  root.querySelector('.bf-task-feedback').hidden=true;
  el.dataset.verdict=this._lessonPassed?'correct':'incorrect';
  el.textContent=(this._lessonPassed?'Верно. ':'Пока неверно. ')+v.training_hint+(this._lessonPassed?'':' Исправьте ответ и нажмите Enter.');
  el.hidden=false;
 },
 onDestroy:function(){if(this._zoom)this._zoom.destroy();},
 refreshAnswer:function(){
  var out=this.reviewChoice(),root=this.getDOMElement(),repeat=out.answer==='duplicate';
  this._reasonGroup.hidden=!repeat;
  this._reasonButtons.forEach(function(button){
   var selected=repeat&&button.dataset.reason===out.duplicate_reason;
   button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));
  });
  root.querySelectorAll('[data-answer]').forEach(function(b){b.classList.toggle('selected',b.dataset.answer===out.answer);b.setAttribute('aria-pressed',b.dataset.answer===out.answer?'true':'false');});
 },
 reviewError:function(out){var a=out.answer;var message=this._invalidFrames?'Координаты рамок отсутствуют или повреждены.':this._imageFailed?'Фото не загрузилось. Обновите страницу, чтобы повторить загрузку.':!this._choices.some(function(c){return c[0]===a;})?'Выберите один из вариантов ответа.':a==='duplicate'&&!this._canRepeat?'Сначала оцените предыдущие рамки этой фотографии.':'';if(message)return {task_id:this.getTask().id,errors:{answer:{code:'CUSTOM',message:message}}};
  if(a==='duplicate'&&!((out.duplicate_reason==='fixed'&&this._hasFixedReference)||(out.duplicate_reason==='earlier'&&this._hasEarlierReference))){
   return {task_id:this.getTask().id,errors:{duplicate_reason:{code:'CUSTOM',message:'Выберите причину повтора.'}}};
  }
  return null;
 },
 validate:function(solution){
  if(this._lessonChoice&&!this._lessonPassed)return {task_id:this.getTask().id,errors:{answer:{code:'CUSTOM',message:'Проверьте ответ на этом шаге клавишей Enter.'}}};
  return this.reviewError((solution||this.getSolution()).output_values)||TolokaHandlebarsTask.prototype.validate.call(this,solution);
 }
});
exports.TaskSuite=inherit(TolokaTaskSuite,{
 onRender:function(){
  var self=this,root=this.getDOMElement();bfPrepareLayout(root,true);this._unbindFullscreen=bfBindFullscreen(this);this._index=0;this._reviewSteps=this.getTasks().slice();
  // Hand-made validation pages contain a single photo. Keep the SDK's task/solution order intact.
  var first=this._reviewSteps[0];
  if(first&&this._reviewSteps.every(function(t){return t.getTemplateData().image_url===first.getTemplateData().image_url;})){
   this._reviewSteps.sort(function(a,b){
    var left=a.getTemplateData(),right=b.getTemplateData();
    if(left.review_type!==right.review_type)return left.review_type==='coverage'?1:-1;
    return (left.box_index||0)-(right.box_index||0);
   });
  }
  this._nav=document.createElement('nav');this._nav.className='bf-pager';
  this._nav.innerHTML='<div class="bf-pager-row"><button type="button" class="bf-prev">← Назад</button><strong class="bf-progress" aria-live="polite"></strong><button type="button" class="bf-next">Далее <kbd>Enter</kbd> →</button></div><div class="bf-steps"></div>';
  root.insertBefore(this._nav,root.firstChild);
  this._nav.querySelector('.bf-prev').onclick=function(){self.show(self._index-1);};
  this._nav.querySelector('.bf-next').onclick=function(){self.advance();};
  this._reviewSteps.forEach(function(t,i){var b=document.createElement('button');b.type='button';b.textContent=i+1;b.setAttribute('aria-label','Перейти к вопросу '+(i+1));b.onclick=function(){self.show(i);};self._nav.querySelector('.bf-steps').appendChild(b);});
  // Selecting only updates highlighting/progress. Navigation is a separate action.
  this._answer=function(){self.refresh();};root.addEventListener('bf-answer',this._answer);
  this._keydown=function(e){
   if(e.target.closest&&e.target.closest('.bf-isolate-fixed,[data-answer],[data-reason]')&&(e.key==='Enter'||e.code==='NumpadEnter'))return;
   if(e.ctrlKey||e.metaKey||e.altKey||e.isComposing||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable)return;
   var digit=/^(?:Digit|Numpad)([1-6])$/.exec(e.code||''),number=digit?Number(digit[1]):/^[1-6]$/.test(e.key)?Number(e.key):0;
   var task=self._reviewSteps[self._index];
   if(!task)return;
   var repeat=task.reviewChoice().answer==='duplicate';
   var enter=e.key==='Enter'||e.code==='NumpadEnter';
   var primary=number>0&&number<=task._choices.length;
   var reasonKey=repeat&&(number===5||number===6);
   if(!(enter||primary||reasonKey||e.key==='ArrowLeft'||e.key==='ArrowRight'))return;
   e.preventDefault();e.stopImmediatePropagation();if(e.repeat)return;
   if(enter)self.advance();
   else if(e.key==='ArrowLeft')self.show(self._index-1);
   else if(e.key==='ArrowRight'&&self._index<self._reviewSteps.length-1)self.advance();
   else if(reasonKey)task._reasonButtons[number-5].click();
   else if(primary)task.choose(number-1);
  };
  document.addEventListener('keydown',this._keydown,true);this.show(0);
  if(this._reviewSteps.length===1&&this._reviewSteps[0].getTemplateData().training&&!this._reviewSteps[0]._lessonChoice)this._nav.hidden=true;
 },
 advance:function(){
  var current=this._reviewSteps[this._index];
  if(!current||current.getWorkspaceOptions().isReadOnly)return;
  if(current._lessonChoice&&!current._lessonPassed){current.checkLesson();this.refresh();return;}
  var last=this._index===this._reviewSteps.length-1||this.readyForRetry(),check=last?this._reviewSteps:[current];
  for(var i=0;i<check.length;i++){
   var error=check[i].validate(check[i].getSolution());
   if(error){check[i].onValidationFail(error);this.show(this._reviewSteps.indexOf(check[i]));return;}
  }
  if(last)current.getAssignment().submit();else this.show(this._index+1);
 },
 readyForRetry:function(){
  return this._reviewSteps.some(function(t){return t._lessonRetry;})&&this._reviewSteps.every(function(t){return t._lessonPassed;});
 },
 focusTask:function(i){TolokaTaskSuite.prototype.focusTask.call(this,i);if(this._nav)this.show(this._reviewSteps.indexOf(this.getTasks()[i]));},
 refresh:function(){
  var self=this,count=0;
  this._reviewSteps.forEach(function(t,i){
   var answered=t._lessonChoice?t._lessonPassed:bfReviewAnswered(t.reviewChoice());if(answered)count++;
   var b=self._nav.querySelectorAll('.bf-steps button')[i];b.classList.toggle('active',i===self._index);b.classList.toggle('answered',answered);b.setAttribute('aria-current',i===self._index?'step':'false');
   var v=t.getTemplateData(),prior=self._reviewSteps.filter(function(p){var a=p.getTemplateData();return a.image_url===v.image_url&&a.review_type==='box'&&(a.box_index||0)<(v.box_index||0);});
   t.updateRepeatAccess(prior.length===(v.box_index||0)&&prior.every(function(p){return p._lessonChoice?p._lessonPassed:bfReviewAnswered(p.reviewChoice());}));
  });
  this._nav.querySelector('.bf-progress').textContent='Вопрос '+(this._index+1)+' из '+this._reviewSteps.length+' · отвечено '+count;
  this._nav.querySelector('.bf-prev').disabled=this._index===0;
  var current=this._reviewSteps[this._index],retry=this.readyForRetry();
  var next=current._lessonChoice&&!current._lessonPassed?'Проверить':retry?'Отправить исправления':this._index===this._reviewSteps.length-1?'Отправить':'Далее';
  this._nav.querySelector('.bf-next').innerHTML=next+' <kbd>Enter</kbd>';
  var hint=current.reviewChoice().answer==='duplicate'?'1–4 — ответ · 5–6 — причина':(current._choices.length===2?'1–2':'1–4')+' — выбрать ответ';
  current.getDOMElement().querySelector('.bf-tag').textContent=hint+' · Enter — '+next.toLowerCase();
 },
 show:function(index){
  if(!this._reviewSteps||!this._reviewSteps.length)return;
  var pending=this._reviewSteps.findIndex(function(t){return t._lessonChoice&&!t._lessonPassed&&!t.getWorkspaceOptions().isReadOnly;});
  this._index=Math.max(0,Math.min(index,pending<0?this._reviewSteps.length-1:pending));var self=this;
  this._reviewSteps.forEach(function(t,i){t.getDOMElement().style.display=i===self._index?'block':'none';});
  this.refresh();
  var visible=this._reviewSteps[this._index],photo=visible.getDOMElement().querySelector('svg');
  photo.classList.remove('bf-hide-focus');
  visible.getDOMElement().querySelector('.bf-isolate-fixed').textContent='Скрыть оранжевую';
  bfFocusTask(visible.getDOMElement());
 },
 onValidationFail:function(errors){
  if(TolokaTaskSuite.prototype.onValidationFail)TolokaTaskSuite.prototype.onValidationFail.call(this,errors);
  var self=this;
  (errors||[]).filter(Boolean).forEach(function(e){
   var t=self._reviewSteps.find(function(item){return item.getTask().id===e.task_id;});
   if(t&&t._lessonPassed&&!t._lessonRetry)t.onValidationFail(e);
  });
  if(this.readyForRetry())this._reviewSteps.forEach(function(t){t._lessonRetry=true;t.saveLessonChoice();});
  var first=(errors||[]).find(function(e){return !!e;});
  if(first){var i=this._reviewSteps.findIndex(function(t){return t.getTask().id===first.task_id;});if(i>=0)this.show(i);}
 },
 onDestroy:function(){if(this._unbindFullscreen)this._unbindFullscreen();document.removeEventListener('keydown',this._keydown,true);if(this._answer)this.getDOMElement().removeEventListener('bf-answer',this._answer);}
});
