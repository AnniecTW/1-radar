(() => {
 const filterForm=document.querySelector('.map-filter-form');
 if(filterForm){
  document.addEventListener('keydown',event=>{if(event.key==='Tab')document.body.classList.add('keyboard-focus-mode');});
  document.addEventListener('pointerdown',()=>document.body.classList.remove('keyboard-focus-mode'));
  filterForm.querySelectorAll('[data-toggle-param]').forEach(button=>button.addEventListener('click',()=>{
   const url=new URL(location.href),param=button.dataset.toggleParam,value=button.dataset.toggleValue;
   if(url.searchParams.get(param)===value)url.searchParams.delete(param);else url.searchParams.set(param,value);
   location.assign(url);
  }));
  const dateSelect=filterForm.querySelector('select[name="date"]');
  const dateCaption=dateSelect?.closest('.date-filter-content')?.querySelector('small');
  const syncDateCaption=()=>{if(dateCaption&&dateSelect?.selectedOptions[0])dateCaption.textContent=dateSelect.selectedOptions[0].dataset.caption||'';};
  syncDateCaption();
  dateSelect?.addEventListener('change',()=>{syncDateCaption();filterForm.requestSubmit();});
  filterForm.querySelector('select[name="category"]')?.addEventListener('change',()=>filterForm.requestSubmit());
  filterForm.querySelectorAll('input[type="checkbox"][name="free"],input[type="checkbox"][name="walk"]').forEach(input=>input.addEventListener('change',()=>filterForm.requestSubmit()));
 }
 const el=document.getElementById('explore-map'); if(!el||!window.maplibregl)return;
 const status=document.getElementById('map-status'), list=document.getElementById('event-list'), search=document.getElementById('search-area');
 const points=JSON.parse(document.getElementById('map-points').textContent), center=JSON.parse(document.getElementById('map-center').textContent);
 if(!window.RADAR_MAP.key){status.textContent='Map unavailable: configure MAPTILER_API_KEY.';return;}
 const map=new maplibregl.Map({container:el,style:`https://api.maptiler.com/maps/streets-v2/style.json?key=${encodeURIComponent(window.RADAR_MAP.key)}`,center:[center[1],center[0]],zoom:12.2});
 document.querySelectorAll('[data-map-zoom]').forEach(button=>button.addEventListener('click',()=>map.zoomTo(map.getZoom()+(button.dataset.mapZoom==='in'?1:-1),{duration:250})));
 const resizeObserver=new ResizeObserver(()=>map.resize());
 resizeObserver.observe(el);
 let markers=new Map(), dragging=false;const seenMarkerIds=new Set();
 function render(items){markers.forEach(m=>m.remove());markers.clear();list.innerHTML='';items.forEach((e,index)=>{
  const node=document.createElement('a');node.className='map-event';node.href=`/events/${encodeURIComponent(e.slug)}/`;node.dataset.eventId=e.id;
  node.innerHTML=`<div class="map-event-image">${e.cover?`<img src="${e.cover}" alt="">`:`<span>${e.title.slice(0,1)}</span>`}</div><div><h3></h3><p>${new Date(e.start).toLocaleString()}</p><p></p><small>${(e.categories||[]).join(' · ')}</small></div>`;
  node.querySelector('h3').textContent=e.title; node.querySelectorAll('p')[1].textContent=`${e.venue} · ${e.going} going`; list.append(node);
  const palette={'Food':'#168b78','Music':'#e06a43','Outdoors':'#3483cf','Study':'#5147e8','Tech':'#5147e8','Arts':'#c34f9a'};const color=palette[e.categories?.[0]]||(e.popularity>5?'#c2410c':'#5147e8');
  const popup=document.createElement('div');popup.className='map-popup';const title=document.createElement('b');title.textContent=e.title;const meta=document.createElement('p');meta.textContent=`${new Date(e.start).toLocaleString()} · ${e.venue}`;const link=document.createElement('a');link.href=`/events/${encodeURIComponent(e.slug)}/`;link.textContent='View event';popup.append(title,meta,link);
  const marker=new maplibregl.Marker({color}).setLngLat([e.lng,e.lat]).setPopup(new maplibregl.Popup({offset:18}).setDOMContent(popup)).addTo(map);const markerEl=marker.getElement();if(!seenMarkerIds.has(e.id)){markerEl.classList.add('marker-enter');seenMarkerIds.add(e.id);}markerEl.setAttribute('role','button');markerEl.setAttribute('tabindex','0');markerEl.setAttribute('aria-label',`Show ${e.title}`);markerEl.style.setProperty('--marker-delay',`${Math.min(index,8)*18}ms`);
  const selectCard=()=>{node.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});node.classList.add('active');window.setTimeout(()=>node.classList.remove('active'),1100);};
  markerEl.addEventListener('click',selectCard);markerEl.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();marker.togglePopup();selectCard();}});
  markerEl.addEventListener('mouseenter',()=>node.classList.add('active'));markerEl.addEventListener('mouseleave',()=>node.classList.remove('active'));
  node.addEventListener('mouseenter',()=>markerEl.classList.add('marker-active'));node.addEventListener('mouseleave',()=>markerEl.classList.remove('marker-active'));node.addEventListener('focusin',()=>markerEl.classList.add('marker-active'));node.addEventListener('focusout',()=>markerEl.classList.remove('marker-active'));markers.set(e.id,marker);
 }); document.getElementById('result-count').textContent=items.length; if(!items.length)list.innerHTML='<div class="empty-results"><i data-lucide="map-pin-off" aria-hidden="true"></i><b>No events found here</b><p>Try moving the map or clearing your filters.</p><a href="/explore/">Clear filters</a></div>';status.hidden=true;status.textContent=items.length?`${items.length} events shown`:'No events in this area.';window.lucide?.createIcons(); }
 map.on('load',async()=>{status.hidden=true;render(points);if(points.length>1){const bounds=new maplibregl.LngLatBounds();points.forEach(p=>bounds.extend([p.lng,p.lat]));map.fitBounds(bounds,{padding:54,maxZoom:13.2,duration:0});}else if(points.length===1){map.setCenter([points[0].lng,points[0].lat]);map.setZoom(12.2);}if(window.RADAR_MAP.walk){let loc=null;if(navigator.geolocation){loc=await new Promise(resolve=>navigator.geolocation.getCurrentPosition(p=>resolve([p.coords.latitude,p.coords.longitude]),()=>resolve(null),{maximumAge:300000,timeout:5000}));}try{await fetchArea(map.getBounds(),loc);}catch{status.hidden=false;status.textContent='Could not load walking-distance results.';}}}); map.on('error',()=>{status.hidden=false;status.textContent='Map tiles failed to load. Check your MapTiler key and allowed referrers.';});
 map.on('dragstart',()=>dragging=true);map.on('moveend',()=>{if(dragging){search.hidden=false;dragging=false;}});
 async function fetchArea(bounds,centerCoords){const url=new URL('/api/map-events/',location.origin);url.searchParams.set('bbox',[bounds.getWest(),bounds.getSouth(),bounds.getEast(),bounds.getNorth()].join(','));url.searchParams.set('date',window.RADAR_MAP.date);url.searchParams.set('category',window.RADAR_MAP.category);url.searchParams.set('q',window.RADAR_MAP.q);url.searchParams.set('sort',window.RADAR_MAP.sort);if(window.RADAR_MAP.free)url.searchParams.set('free','1');if(window.RADAR_MAP.walk){url.searchParams.set('walk','1');if(centerCoords){url.searchParams.set('lat',centerCoords[0]);url.searchParams.set('lng',centerCoords[1]);}}list.setAttribute('aria-busy','true');list.innerHTML='<div class="event-skeletons" aria-label="Loading events">'+Array.from({length:3},()=>'<div class="event-skeleton"><i></i><span><b></b><b></b><b></b></span></div>').join('')+'</div>';status.hidden=false;status.textContent='Updating events…';try{const r=await fetch(url);if(!r.ok)throw new Error();const data=await r.json();render(data.events);return data.events;}finally{list.removeAttribute('aria-busy');}}
 search.addEventListener('click',async()=>{search.disabled=true;search.classList.add('is-loading');search.querySelector('.search-label').textContent='Searching…';try{let loc=null;if(window.RADAR_MAP.walk&&navigator.geolocation){loc=await new Promise(resolve=>navigator.geolocation.getCurrentPosition(p=>resolve([p.coords.latitude,p.coords.longitude]),()=>resolve(null),{maximumAge:300000,timeout:5000}));}await fetchArea(map.getBounds(),loc);search.hidden=true;}catch{status.hidden=false;status.textContent='Could not load events. Please try again.';}finally{search.disabled=false;search.classList.remove('is-loading');search.querySelector('.search-label').textContent='Search this area';}});
})();
