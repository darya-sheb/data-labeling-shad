/* Yandex tasks are shrink-to-fit by default. Size the SDK roots, not only our card. */
function bfPrepareLayout(root, suite) {
  root.classList.add(suite ? 'bf-suite-host' : 'bf-task-host');
  root.style.width='100%';root.style.maxWidth='100%';root.style.minWidth='0';
  root.style.boxSizing='border-box';root.style.display='block';
  if(suite){bfFocusTask(root);root.ownerDocument.defaultView.setTimeout(function(){if(root.ownerDocument.activeElement===root.ownerDocument.body)bfFocusTask(root);},0);}
}

/* Give the iframe keyboard focus on the first task without scrolling the page. */
function bfFocusTask(root) {
  if(!root||!root.isConnected)return;
  root.tabIndex=-1;
  root.focus({preventScroll:true});
}

/* Start the platform's fullscreen transition inside the task iframe: the host's
   toolbar lives in another document and otherwise retains the keyboard. */
function bfBindFullscreen(suite) {
  var root=suite.getDOMElement(),doc=root.ownerDocument,win=doc.defaultView;
  var service=suite.taskInterface,html=doc.documentElement;
  var usePlatform=service&&typeof service.toggleFullscreen==='function';
  var nativeRequest=html.requestFullscreen||html.webkitRequestFullscreen;
  var nativeExit=doc.exitFullscreen||doc.webkitExitFullscreen;
  var nativeAllowed=(doc.fullscreenEnabled||doc.webkitFullscreenEnabled)&&nativeRequest&&nativeExit;
  var buttons=root.querySelectorAll('.bf-fullscreen');
  buttons.forEach(function(button){button.hidden=!(usePlatform||nativeAllowed);});
  var frame=null,restoreUntil=0;

  function focusTask() {
    if(!root.isConnected||doc.hidden||root.querySelector('dialog[open]'))return;
    var task=suite.getTasks().find(function(item){var el=item.getDOMElement();return !el.hidden&&el.style.display!=='none';});
    if(task)bfFocusTask(task.getDOMElement());
  }
  function restore() {
    if(frame!==null)win.cancelAnimationFrame(frame);
    frame=win.requestAnimationFrame(function(){
      frame=null;
      // Preserve deliberate focus on controls such as a checkbox or the video player.
      if(!doc.hasFocus()||doc.activeElement===doc.body||doc.activeElement===html)focusTask();
    });
  }
  function resized() {
    // Host-driven fullscreen may only resize a cross-origin iframe.
    if(Date.now()<restoreUntil)restore();
  }
  function toggle() {
    restoreUntil=Date.now()+1500;
    focusTask();
    if(usePlatform){service.toggleFullscreen();restore();return;}
    if(!nativeAllowed)return;
    var active=doc.fullscreenElement||doc.webkitFullscreenElement;
    Promise.resolve(active?nativeExit.call(doc):nativeRequest.call(html)).then(restore,restore);
  }
  function buttonKey(event) {
    if(!root.contains(event.target)||!event.target.matches||!event.target.matches('.bf-fullscreen'))return;
    if(event.key!=='Enter'&&event.key!==' ')return;
    event.preventDefault();event.stopImmediatePropagation();
    if(!event.repeat)toggle();
  }
  buttons.forEach(function(button){button.addEventListener('click',toggle);});
  win.addEventListener('keydown',buttonKey,true);
  win.addEventListener('resize',resized);
  doc.addEventListener('fullscreenchange',restore);
  doc.addEventListener('webkitfullscreenchange',restore);
  return function(){
    if(frame!==null)win.cancelAnimationFrame(frame);
    buttons.forEach(function(button){button.removeEventListener('click',toggle);});
    win.removeEventListener('keydown',buttonKey,true);
    win.removeEventListener('resize',resized);
    doc.removeEventListener('fullscreenchange',restore);
    doc.removeEventListener('webkitfullscreenchange',restore);
  };
}

/* Shared zoom controller. Coordinates remain normalized; the BBOX adapter uses the native editor.zoom. */
function BFZoom(root, viewport, adapter) {
  var self=this;this.scale=1;this.drag=null;this.adapter=adapter;this.viewport=viewport;this.root=root;
  this.spacePan=false;
  this.active=function(){var node=root;while(node&&node!==document){if(node.hidden||node.style&&node.style.display==='none')return false;node=node.parentNode;}return true;};
  this.set=function(value,point){var old=self.scale;self.scale=Math.max(0.25,Math.min(8,value));var r=viewport.getBoundingClientRect(),x=point?point.clientX-r.left:viewport.clientWidth/2,y=point?point.clientY-r.top:viewport.clientHeight/2;var sx=(viewport.scrollLeft+x)/old,sy=(viewport.scrollTop+y)/old;adapter.set(self.scale);viewport.scrollLeft=Math.max(0,sx*self.scale-x);viewport.scrollTop=Math.max(0,sy*self.scale-y);var label=root.querySelector('.bf-zoom-label');if(label)label.textContent=Math.round(self.scale*100)+'%';};
  this.fit=function(){if(adapter.fit)adapter.fit();self.set(1);viewport.scrollLeft=0;viewport.scrollTop=0;};
  root.querySelectorAll('[data-zoom]').forEach(function(b){b.onclick=function(){var action=b.dataset.zoom;if(action==='fit')self.fit();else self.set(self.scale*(action==='in'?1.25:0.8));};});
  this.wheel=function(e){if(!self.active())return;if(adapter.wheelPan&&!e.ctrlKey&&!e.metaKey){e.preventDefault();var unit=e.deltaMode===1?16:e.deltaMode===2?viewport.clientHeight:1;viewport.scrollLeft+=(e.deltaX+(e.shiftKey?e.deltaY:0))*unit;viewport.scrollTop+=(e.shiftKey?0:e.deltaY)*unit;return;}if(e.shiftKey)return;e.preventDefault();self.set(self.scale*Math.exp(-Math.max(-100,Math.min(100,e.deltaY*(e.deltaMode===1?16:1)))*0.005),e);};
  this.key=function(e){if(!self.active()||e.ctrlKey||e.metaKey||e.altKey||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;var used=true;if(adapter.wheelPan&&(e.code==='Space'||e.key===' ')){self.spacePan=true;viewport.classList.add('bf-pan-ready');}else if(e.key==='+'||e.key==='=')self.set(self.scale*1.25);else if(e.key==='-'||e.key==='_')self.set(self.scale/1.25);else if(e.key==='0')self.fit();else used=false;if(used){e.preventDefault();e.stopImmediatePropagation();}};
  this.gestureStart=function(e){if(!self.active())return;e.preventDefault();self.startScale=self.scale;};this.gestureChange=function(e){if(!self.active())return;e.preventDefault();self.set((self.startScale||1)*e.scale,e);};
  this.down=function(e){if(!self.active())return;var right=adapter.wheelPan&&e.button===2;if(adapter.nativePan&&e.button!==1&&!right&&!(self.spacePan&&e.button===0))return;if(e.button!==0&&e.button!==1&&!right)return;self.drag={x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.classList.add('bf-panning');e.preventDefault();e.stopImmediatePropagation();};
  this.move=function(e){if(!self.drag)return;viewport.scrollLeft=self.drag.left+self.drag.x-e.clientX;viewport.scrollTop=self.drag.top+self.drag.y-e.clientY;e.preventDefault();};this.up=function(){self.drag=null;viewport.classList.remove('bf-panning');};
  this.keyUp=function(e){if(e.code==='Space'||e.key===' '){self.spacePan=false;viewport.classList.remove('bf-pan-ready');}};
  this.blur=function(){self.spacePan=false;viewport.classList.remove('bf-pan-ready');self.up();};
  this.contextMenu=function(e){if(adapter.wheelPan)e.preventDefault();};
  viewport.addEventListener('wheel',this.wheel,{passive:false});viewport.addEventListener('gesturestart',this.gestureStart,{passive:false});viewport.addEventListener('gesturechange',this.gestureChange,{passive:false});viewport.addEventListener('mousedown',this.down,true);document.addEventListener('mousemove',this.move);document.addEventListener('mouseup',this.up);document.addEventListener('keydown',this.key,true);document.addEventListener('keyup',this.keyUp,true);root.ownerDocument.defaultView.addEventListener('blur',this.blur);viewport.addEventListener('contextmenu',this.contextMenu);
  this.destroy=function(){viewport.removeEventListener('wheel',self.wheel);viewport.removeEventListener('gesturestart',self.gestureStart);viewport.removeEventListener('gesturechange',self.gestureChange);viewport.removeEventListener('mousedown',self.down,true);document.removeEventListener('mousemove',self.move);document.removeEventListener('mouseup',self.up);document.removeEventListener('keydown',self.key,true);document.removeEventListener('keyup',self.keyUp,true);root.ownerDocument.defaultView.removeEventListener('blur',self.blur);viewport.removeEventListener('contextmenu',self.contextMenu);};
  this.fit();
}

/* Fit each photo to its aspect ratio and the room left by readable controls. */
function bfFitImage(maxWidth,maxHeight,width,height){var ratio=width>0&&height>0?width/height:4/3,w=Math.min(maxWidth,maxHeight*ratio);return {width:Math.max(1,Math.floor(w)),height:Math.max(1,Math.floor(w/ratio))};}
function BFScreenFit(root, viewport, changed) {
  var win=root.ownerDocument.defaultView,self=this,frame=null,lastWidth=0,lastHeight=0;
  var grid=root.querySelector('.bf-workbench,.bf-review-grid'),column=root.querySelector('.bf-canvas-column,.bf-review-image'),img=root.querySelector('.image-annotation-editor__image,.bf-photo img');
  this.update=function(){
    if(!root.isConnected||root.getBoundingClientRect().height===0)return;
    var card=root.querySelector('.bf-bbox,.bf-review'),available=root.clientWidth;
    if(card){
      var review=card.classList.contains('bf-review');
      card.classList.toggle('bf-compact',available<=(review?1300:1200));
      card.classList.toggle('bf-narrow',available<=(review?950:1000));
    }
    var rect=root.getBoundingClientRect(),vr=viewport.getBoundingClientRect(),height,width=vr.width;
    if(grid&&column&&grid.clientWidth>0){
      var gr=grid.getBoundingClientRect(),cr=column.getBoundingClientRect(),sideWidth=0,count=0;
      Array.prototype.forEach.call(grid.children,function(el){if(el===column)return;var w=el.getBoundingClientRect().width;if(w>0){sideWidth+=w;count++;}});
      var gap=parseFloat(win.getComputedStyle(grid).columnGap)||0;
      var roomHeight=Math.max(review?120:400,win.innerHeight-Math.max(0,gr.top)-(rect.bottom-gr.bottom)-(cr.height-vr.height)-65);
      var roomWidth=Math.max(120,grid.clientWidth-sideWidth-gap*count);
      var size=bfFitImage(roomWidth,roomHeight,img&&img.naturalWidth,img&&img.naturalHeight);width=review?size.width:roomWidth;height=review?size.height:roomHeight;if(!review)grid.style.setProperty('--bf-work-height',height+'px');
      grid.style.setProperty('--bf-photo-width',width+'px');
    }else height=Math.max(120,Math.floor(win.innerHeight-Math.max(0,rect.top)-(rect.height-vr.height)-148));
    if(Math.abs(height-lastHeight)>1||Math.abs(width-lastWidth)>1){lastHeight=height;lastWidth=width;viewport.style.height=height+'px';if(changed)changed();}
  };
  // Embedded/background previews can pause animation frames; size immediately too.
  this.schedule=function(){self.update();if(frame===null)frame=win.requestAnimationFrame(function(){frame=null;self.update();});};
  this.observer=typeof ResizeObserver==='function'?new ResizeObserver(this.schedule):null;
  if(this.observer){this.observer.observe(root);this.observer.observe(root.parentNode||root);}
  win.addEventListener('resize',this.schedule);root.addEventListener('toggle',this.schedule,true);this.schedule();
  this.destroy=function(){if(frame!==null)win.cancelAnimationFrame(frame);if(self.observer)self.observer.disconnect();win.removeEventListener('resize',self.schedule);root.removeEventListener('toggle',self.schedule,true);};
}
