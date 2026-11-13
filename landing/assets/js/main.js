const t=document.querySelector('.menu-toggle'),m=document.getElementById('menu');
t.addEventListener('click',()=>{const o=m.classList.toggle('open');t.setAttribute('aria-expanded',o)});
m.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{m.classList.remove('open');t.setAttribute('aria-expanded','false')}));
document.getElementById('form-demo').addEventListener('submit',e=>{
  e.preventDefault();
  const f=e.target,v=n=>f.elements[n].value.trim();
  const msg=`Olá! Quero uma demonstração da Equicidade.%0A%0ANome: ${v('nome')}%0AMunicípio: ${v('municipio')}%0AE-mail: ${v('email')}%0ATelefone: ${v('telefone')}`;
  window.open('https://wa.me/5582988189617?text='+msg.replace(/ /g,'%20'),'_blank','noopener');
});
document.getElementById('ano').textContent=new Date().getFullYear();

const calmo=matchMedia('(prefers-reduced-motion: reduce)').matches;
const topo=document.querySelector('.top');
addEventListener('scroll',()=>topo.classList.toggle('scrolled',scrollY>8),{passive:true});
if(!calmo&&'IntersectionObserver' in window){
  const alvos=document.querySelectorAll('.sec-head,.card,.step,.cta');
  alvos.forEach(el=>{
    const irmaos=[...el.parentElement.children].filter(x=>x.matches('.card,.step'));
    const i=irmaos.indexOf(el);
    if(i>0)el.style.setProperty('--d',(i*0.1)+'s');
    el.classList.add('reveal');
  });
  const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.15,rootMargin:'0px 0px -40px 0px'});
  alvos.forEach(el=>io.observe(el));
  const n=document.querySelector('[data-count]');
  if(n){
    const fim=+n.dataset.count,fmt=new Intl.NumberFormat('pt-BR');
    n.textContent='0';
    setTimeout(()=>{const t0=performance.now(),dur=1800;
      const passo=t=>{const p=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-p,3);n.textContent=fmt.format(Math.round(fim*e));if(p<1)requestAnimationFrame(passo)};
      requestAnimationFrame(passo)},900);
  }
}

const cp=document.getElementById('copiar'),msg=document.getElementById('sh-msg');
if(cp)cp.addEventListener('click',async()=>{
  const url='https://equicidade.com.br/',txt='Equicidade: veja onde falta escola, creche e posto de saúde na sua cidade.';
  if(navigator.share&&matchMedia('(pointer:coarse)').matches){try{await navigator.share({title:'Equicidade',text:txt,url});return}catch(e){}}
  try{await navigator.clipboard.writeText(url);msg.textContent='Link copiado'}catch(e){msg.textContent=url}
  setTimeout(()=>msg.textContent='',2500);
});

const bs=document.getElementById('btn-share'),ms=document.getElementById('menu-share');
const URL_SITE='https://equicidade.com.br/',TXT_SITE='Equicidade: veja onde falta escola, creche e posto de saúde na sua cidade.';
function fecha(){ms.hidden=true;bs.setAttribute('aria-expanded','false')}
bs.addEventListener('click',async e=>{
  e.stopPropagation();
  if(navigator.share&&matchMedia('(pointer:coarse)').matches){try{await navigator.share({title:'Equicidade',text:TXT_SITE,url:URL_SITE});return}catch(err){}}
  const abre=ms.hidden;ms.hidden=!abre;bs.setAttribute('aria-expanded',String(abre));
});
document.addEventListener('click',e=>{if(!ms.hidden&&!ms.contains(e.target))fecha()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!ms.hidden){fecha();bs.focus()}});
document.getElementById('copiar2').addEventListener('click',async()=>{
  const m=document.getElementById('sh-msg2');
  try{await navigator.clipboard.writeText(URL_SITE);m.textContent='Link copiado'}catch(err){m.textContent=URL_SITE}
  setTimeout(()=>m.textContent='',2500);
});
