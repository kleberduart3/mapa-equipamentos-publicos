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
