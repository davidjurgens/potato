function j(t) {
  return t && t.__esModule && Object.prototype.hasOwnProperty.call(t, "default") ? t.default : t;
}
var E = { exports: {} }, m = { exports: {} };
(function(t, i) {
  (function(n) {
    i = n(), t.exports = i;
  })(function() {
    var n = function(a) {
      return a instanceof Function;
    }, e = function(a) {
      var h = Array.prototype.slice.call(arguments, 1);
      for (var c in h) {
        var l = h[c];
        if (typeof l == "object")
          for (var f in l)
            a[f] = l[f];
      }
      return a;
    }, r = {
      // internal object for indicating that class objects don't have a class object themselves,
      // may not be used by users
      _isClassObject: !1
    }, o = !1, s = function() {
    };
    return s._subClasses = [], s.prototype.init = function() {
    }, s._extend = function(a, h, c) {
      a === void 0 && (a = {}), h === void 0 && (h = {}), c === void 0 && (c = {}), c = e({}, r, c);
      var l = function() {
        o || (this._class = l, this.init instanceof Function && this.init.apply(this, arguments));
      }, f = this;
      o = !0;
      var d = new f();
      o = !1;
      var u = f.prototype;
      l.prototype = d, l.prototype.constructor = l, l._superClass = f, l._subClasses = [], f._subClasses.push(l), l._extend = f._extend, l._extends = function(C) {
        return this._superClass == s ? !1 : C == this._superClass || C == s ? !0 : this._superClass._extends(C);
      };
      for (var p in a) {
        var g = Object.getOwnPropertyDescriptor(a, p), v = g.value;
        if (v !== null && typeof v == "object" && v.descriptor)
          Object.defineProperty(d, p, v);
        else if (!("value" in g) && ("set" in g || "get" in g))
          Object.defineProperty(d, p, g);
        else {
          d[p] = v;
          var O = u[p];
          n(v) && n(O) && v !== O && (v._super = O);
        }
      }
      if (!c._isClassObject) {
        var R = f._members === void 0 ? s : f._members._class, b = e({}, c, { _isClassObject: !0 }), y = R._extend(h, {}, b);
        y._instanceClass = l, l._members = new y();
      }
      return l;
    }, s._convert = function(a, h) {
      var c = a.prototype;
      return c.init = function() {
        var l = this._origin = s._construct(a, arguments);
        Object.keys(l).forEach(function(f) {
          l.hasOwnProperty(f) && Object.defineProperty(this, f, {
            get: function() {
              return l[f];
            }
          });
        }, this);
      }, s._extend(c, {}, h);
    }, s._construct = function(a, h) {
      h === void 0 && (h = []);
      var c = function() {
        return a.apply(this, h);
      };
      return c.prototype = a.prototype, new c();
    }, s._superDescriptor = function(a, h) {
      if ("_class" in a && a instanceof a._class && (a = a._class), "_extends" in a && a._extends instanceof Function && a._extends(this))
        return Object.getOwnPropertyDescriptor(a._superClass.prototype, h);
    }, s;
  });
})(m, m.exports);
var P = m.exports, S = P, _ = S._extend({
  //-----------------------------------
  // Constructor
  //-----------------------------------
  init: function(t, i, n) {
    t = t instanceof Array ? t : [t], this._map = {}, this._list = [], this.callback = i, this.keyFields = t, this.isHashArray = !0, this.options = n || {
      ignoreDuplicates: !1
    }, i && i("construct");
  },
  //-----------------------------------
  // add()
  //-----------------------------------
  addOne: function(t) {
    var i = !1;
    for (var n in this.keyFields) {
      n = this.keyFields[n];
      var e = this.objectAt(t, n);
      if (e)
        if (this.has(e)) {
          if (this.options.ignoreDuplicates)
            return;
          if (this._map[e].indexOf(t) != -1) {
            i = !0;
            continue;
          }
          this._map[e].push(t);
        } else this._map[e] = [t];
    }
    (!i || this._list.indexOf(t) == -1) && this._list.push(t);
  },
  add: function() {
    for (var t = 0; t < arguments.length; t++)
      this.addOne(arguments[t]);
    return this.callback && this.callback("add", Array.prototype.slice.call(arguments, 0)), this;
  },
  addAll: function(t) {
    if (t.length < 100)
      this.add.apply(this, t);
    else
      for (var i = 0; i < t.length; i++)
        this.add(t[i]);
    return this;
  },
  addMap: function(t, i) {
    return this._map[t] = i, this.callback && this.callback("addMap", {
      key: t,
      obj: i
    }), this;
  },
  //-----------------------------------
  // Intersection, union, etc.
  //-----------------------------------
  /**
   * Returns a new HashArray that contains the intersection between this (A) and the hasharray passed in (B). Returns A ^ B.
   */
  intersection: function(t) {
    var i = this;
    if (!t || !t.isHashArray)
      throw Error("Cannot HashArray.intersection() on a non-hasharray object. You passed in: ", t);
    var n = this.clone(null, !0), e = this.clone(null, !0).addAll(this.all.concat(t.all));
    return e.all.forEach(function(r) {
      i.collides(r) && t.collides(r) && n.add(r);
    }), n;
  },
  /**
   * Returns a new HashArray that contains the complement (difference) between this hash array (A) and the hasharray passed in (B). Returns A - B.
   */
  complement: function(t) {
    if (!t || !t.isHashArray)
      throw Error("Cannot HashArray.complement() on a non-hasharray object. You passed in: ", t);
    var i = this.clone(null, !0);
    return this.all.forEach(function(n) {
      t.collides(n) || i.add(n);
    }), i;
  },
  //-----------------------------------
  // Retrieval
  //-----------------------------------
  get: function(t) {
    if (this.has(t))
      return !(this._map[t] instanceof Array) || this._map[t].length != 1 ? this._map[t] : this._map[t][0];
  },
  getAll: function(t) {
    if (t = t instanceof Array ? t : [t], t[0] == "*")
      return this.all;
    var i = new _(this.keyFields);
    for (var n in t)
      i.add.apply(i, this.getAsArray(t[n]));
    return i.all;
  },
  getAsArray: function(t) {
    return this._map[t] || [];
  },
  getUniqueRandomIntegers: function(t, i, n) {
    var e = [], r = {};
    for (t = Math.min(Math.max(n - i, 1), t); e.length < t; ) {
      var o = Math.floor(i + Math.random() * (n + 1));
      r[o] || (r[o] = !0, e.push(o));
    }
    return e;
  },
  sample: function(t, i) {
    var n = this.all, e = [];
    i && (n = this.getAll(i));
    for (var r = this.getUniqueRandomIntegers(t, 0, n.length - 1), o = 0; o < r.length; o++)
      e.push(n[r[o]]);
    return e;
  },
  //-----------------------------------
  // Peeking
  //-----------------------------------
  has: function(t) {
    return this._map.hasOwnProperty(t);
  },
  collides: function(t) {
    for (var i in this.keyFields)
      if (this.has(this.objectAt(t, this.keyFields[i])))
        return !0;
    return !1;
  },
  hasMultiple: function(t) {
    return this._map[t] instanceof Array;
  },
  //-----------------------------------
  // Removal
  //-----------------------------------
  removeByKey: function() {
    for (var t = [], i = 0; i < arguments.length; i++) {
      var n = arguments[i], e = this._map[n].concat();
      if (e) {
        t = t.concat(e);
        for (var r in e) {
          var o = e[r];
          for (var s in this.keyFields) {
            var a = this.objectAt(o, this.keyFields[s]);
            if (a && this.has(a)) {
              var s = this._map[a].indexOf(o);
              s != -1 && this._map[a].splice(s, 1), this._map[a].length == 0 && delete this._map[a];
            }
          }
          this._list.splice(this._list.indexOf(o), 1);
        }
      }
      delete this._map[n];
    }
    return this.callback && this.callback("removeByKey", t), this;
  },
  remove: function() {
    for (var t = 0; t < arguments.length; t++) {
      var i = arguments[t];
      for (var e in this.keyFields) {
        var n = this.objectAt(i, this.keyFields[e]);
        if (n) {
          var e = this._map[n].indexOf(i);
          if (e != -1)
            this._map[n].splice(e, 1);
          else
            throw new Error("HashArray: attempting to remove an object that was never added!" + n);
          this._map[n].length == 0 && delete this._map[n];
        }
      }
      var e = this._list.indexOf(i);
      if (e != -1)
        this._list.splice(e, 1);
      else
        throw new Error("HashArray: attempting to remove an object that was never added!" + n);
    }
    return this.callback && this.callback("remove", arguments), this;
  },
  removeAll: function() {
    var t = this._list.concat();
    return this._map = {}, this._list = [], this.callback && this.callback("remove", t), this;
  },
  //-----------------------------------
  // Utility
  //-----------------------------------
  objectAt: function(t, i) {
    if (typeof i == "string")
      return t[i];
    for (var n = i.concat(); n.length && t; )
      t = t[n.shift()];
    return t;
  },
  //-----------------------------------
  // Iteration
  //-----------------------------------
  forEach: function(t, i) {
    t = t instanceof Array ? t : [t];
    var n = this.getAll(t);
    return n.forEach(i), this;
  },
  forEachDeep: function(t, i, n) {
    t = t instanceof Array ? t : [t];
    var e = this, r = this.getAll(t);
    return r.forEach(function(o) {
      n(e.objectAt(o, i), o);
    }), this;
  },
  //-----------------------------------
  // Cloning
  //-----------------------------------
  clone: function(t, i) {
    var n = new _(this.keyFields.concat(), t || this.callback);
    return i || n.add.apply(n, this.all.concat()), n;
  },
  //-----------------------------------
  // Mathematical
  //-----------------------------------
  sum: function(t, i, n) {
    var e = this, r = 0;
    return this.forEachDeep(t, i, function(o, s) {
      n !== void 0 && (o *= e.objectAt(s, n)), r += o;
    }), r;
  },
  average: function(t, i, n) {
    var e = 0, r = 0, o = 0, s = this;
    return n !== void 0 && this.forEachDeep(t, n, function(a) {
      o += a;
    }), this.forEachDeep(t, i, function(a, h) {
      n !== void 0 && (a *= s.objectAt(h, n) / o), e += a, r++;
    }), n !== void 0 ? e : e / r;
  },
  //-----------------------------------
  // Filtering
  //-----------------------------------
  filter: function(t, i) {
    var n = this, e = typeof i == "function" ? i : o, r = new _(this.keyFields);
    return r.addAll(this.getAll(t).filter(e)), r;
    function o(s) {
      var a = n.objectAt(s, i);
      return a !== void 0 && a !== !1;
    }
  }
});
Object.defineProperty(_.prototype, "all", {
  get: function() {
    return this._list;
  }
});
Object.defineProperty(_.prototype, "map", {
  get: function() {
    return this._map;
  }
});
var T = _;
typeof window < "u" && (window.HashArray = _);
var D = T, x = D, H = 64, F = /^[\s]*$/, I = [
  {
    regex: /[åäàáâãæ]/ig,
    alternate: "a"
  },
  {
    regex: /[èéêë]/ig,
    alternate: "e"
  },
  {
    regex: /[ìíîï]/ig,
    alternate: "i"
  },
  {
    regex: /[òóôõö]/ig,
    alternate: "o"
  },
  {
    regex: /[ùúûü]/ig,
    alternate: "u"
  },
  {
    regex: /[æ]/ig,
    alternate: "ae"
  }
];
String.prototype.replaceCharAt = function(t, i) {
  return this.substr(0, t) + i + this.substr(t + i.length);
};
var A = function(t, i) {
  this.options = i || {}, this.options.ignoreCase = this.options.ignoreCase === void 0 ? !0 : this.options.ignoreCase, this.options.maxCacheSize = this.options.maxCacheSize || H, this.options.cache = this.options.hasOwnProperty("cache") ? this.options.cache : !0, this.options.splitOnRegEx = this.options.hasOwnProperty("splitOnRegEx") ? this.options.splitOnRegEx : /\s/g, this.options.splitOnGetRegEx = this.options.hasOwnProperty("splitOnGetRegEx") ? this.options.splitOnGetRegEx : this.options.splitOnRegEx, this.options.min = this.options.min || 1, this.options.keepAll = this.options.hasOwnProperty("keepAll") ? this.options.keepAll : !1, this.options.keepAllKey = this.options.hasOwnProperty("keepAllKey") ? this.options.keepAllKey : "id", this.options.idFieldOrFunction = this.options.hasOwnProperty("idFieldOrFunction") ? this.options.idFieldOrFunction : void 0, this.options.expandRegexes = this.options.expandRegexes || I, this.options.insertFullUnsplitKey = this.options.hasOwnProperty("insertFullUnsplitKey") ? this.options.insertFullUnsplitKey : !1, this.keyFields = t ? t instanceof Array ? t : [t] : [], this.root = {}, this.size = 0, this.options.cache && (this.getCache = new x("key"));
};
function w(t, i) {
  return i.length === 1 ? t[i[0]] : w(t[i[0]], i.slice(1, i.length));
}
A.prototype = {
  add: function(t, i) {
    this.options.cache && this.clearCache(), typeof i == "number" && (i = void 0);
    var n = i || this.keyFields;
    for (var e in n) {
      var r = n[e], o = r instanceof Array, s = o ? w(t, r) : t[r];
      if (s) {
        s = s.toString();
        for (var a = this.expandString(s), h = 0; h < a.length; h++) {
          var c = a[h];
          this.map(c, t);
        }
      }
    }
  },
  /**
   * By default using the options.expandRegexes, given a string like 'ö är bra', this will expand it to:
   *
   * ['ö är bra', 'o är bra', 'ö ar bra', 'o ar bra']
   *
   * By default this was built to allow for internationalization, but it could be also be expanded to
   * allow for word alternates, etc. like spelling alternates ('teh' and 'the').
   *
   * This is used for insertion! This should not be used for lookup since if a person explicitly types
   * 'ä' they probably do not want to see all results for 'a'.
   *
   * @param value The string to find alternates for.
   * @returns {Array} Always returns an array even if no matches.
   */
  expandString: function(t) {
    var i = [t];
    if (this.options.expandRegexes && this.options.expandRegexes.length)
      for (var n = 0; n < this.options.expandRegexes.length; n++)
        for (var e = this.options.expandRegexes[n], r; (r = e.regex.exec(t)) !== null; ) {
          var o = t.replaceCharAt(r.index, e.alternate);
          i.push(o);
        }
    return i;
  },
  addAll: function(t, i) {
    for (var n = 0; n < t.length; n++)
      this.add(t[n], i);
  },
  reset: function() {
    this.root = {}, this.size = 0;
  },
  clearCache: function() {
    this.getCache = new x("key");
  },
  cleanCache: function() {
    for (; this.getCache.all.length > this.options.maxCacheSize; )
      this.getCache.remove(this.getCache.all[0]);
  },
  addFromObject: function(t, i) {
    this.options.cache && this.clearCache(), i = i || "value", this.keyFields.indexOf("_key_") == -1 && this.keyFields.push("_key_");
    for (var n in t) {
      var e = { _key_: n };
      e[i] = t[n], this.add(e);
    }
  },
  map: function(t, i) {
    if (this.options.splitOnRegEx && this.options.splitOnRegEx.test(t)) {
      var n = t.split(this.options.splitOnRegEx), e = n.filter(function(f) {
        return F.test(f);
      }), r = n.filter(function(f) {
        return f === t;
      }), o = r.length + e.length === n.length;
      if (!o) {
        for (var s = 0, a = n.length; s < a; s++)
          F.test(n[s]) || this.map(n[s], i);
        if (!this.options.insertFullUnsplitKey)
          return;
      }
    }
    this.options.cache && this.clearCache(), this.options.keepAll && (this.indexed = this.indexed || new x([this.options.keepAllKey]), this.indexed.add(i)), this.options.ignoreCase && (t = t.toLowerCase());
    var h = this.keyToArr(t), c = this;
    l(h, i, this.root);
    function l(f, d, u) {
      if (f.length == 0) {
        u.value = u.value || [], u.value.push(d);
        return;
      }
      var p = f.shift();
      u[p] || c.size++, u[p] = u[p] || {}, l(f, d, u[p]);
    }
  },
  keyToArr: function(t) {
    var i;
    if (this.options.min && this.options.min > 1) {
      if (t.length < this.options.min)
        return [];
      i = [t.substr(0, this.options.min)], i = i.concat(t.substr(this.options.min).split(""));
    } else i = t.split("");
    return i;
  },
  findNode: function(t) {
    return i(this.keyToArr(t), this.root);
    function i(n, e) {
      if (e) {
        if (n.length == 0) return e;
        var r = n.shift();
        return i(n, e[r]);
      }
    }
  },
  _getCacheKey: function(t, i) {
    var n = t;
    return i && (n = t + "_" + i), n;
  },
  _get: function(t, i) {
    t = this.options.ignoreCase ? t.toLowerCase() : t;
    var n, e;
    if (this.options.cache && (n = this.getCache.get(this._getCacheKey(t, i))))
      return n.value;
    for (var r = void 0, o = this.options.indexField ? [this.options.indexField] : this.keyFields, s = this.options.splitOnGetRegEx ? t.split(this.options.splitOnGetRegEx) : [t], a = 0, h = s.length; a < h; a++)
      if (!(this.options.min && s[a].length < this.options.min)) {
        var c = new x(o);
        (e = this.findNode(s[a])) && d(e, c), r = r ? r.intersection(c) : c;
      }
    var l = r ? r.all : [];
    if (this.options.cache) {
      var f = this._getCacheKey(t, i);
      this.getCache.add({ key: f, value: l }), this.cleanCache();
    }
    return l;
    function d(u, p) {
      if (!(i && p.all.length === i)) {
        if (u.value && u.value.length)
          if (!i || p.all.length + u.value.length < i)
            p.addAll(u.value);
          else {
            p.addAll(u.value.slice(0, i - p.all.length));
            return;
          }
        for (var g in u) {
          if (i && p.all.length === i)
            return;
          g != "value" && d(u[g], p);
        }
      }
    }
  },
  get: function(t, i, n) {
    var e = this.options.indexField ? [this.options.indexField] : this.keyFields, r = void 0, o = void 0;
    if (i && !this.options.idFieldOrFunction)
      throw new Error("To use the accumulator, you must specify and idFieldOrFunction");
    t = t instanceof Array ? t : [t];
    for (var s = 0, a = t.length; s < a; s++) {
      var h = this._get(t[s], n);
      i ? o = i(o, t[s], h, this) : r = r ? r.addAll(h) : new x(e).addAll(h);
    }
    return i ? o : r.all;
  },
  search: function(t, i, n) {
    return this.get(t, i, n);
  },
  getId: function(t) {
    return typeof this.options.idFieldOrFunction == "function" ? this.options.idFieldOrFunction(t) : t[this.options.idFieldOrFunction];
  }
};
A.UNION_REDUCER = function(t, i, n, e) {
  if (t === void 0)
    return n;
  var r = {}, o, s, a = Math.max(t.length, n.length), h = [], c = 0;
  for (o = 0; o < a; o++)
    o < t.length && (s = e.getId(t[o]), r[s] = r[s] ? r[s] : 0, r[s]++, r[s] === 2 && (h[c++] = t[o])), o < n.length && (s = e.getId(n[o]), r[s] = r[s] ? r[s] : 0, r[s]++, r[s] === 2 && (h[c++] = n[o]));
  return h;
};
E.exports = A;
E.exports.default = A;
var N = E.exports, U = N;
const z = /* @__PURE__ */ j(U);
(function() {
  function t(o) {
    const s = document.getElementById(o);
    if (s !== null)
      try {
        return JSON.parse(s.textContent);
      } catch (a) {
        console.warn(`could not parse json element '${o}'. Error: ${a}`);
      }
  }
  function i(o) {
    const s = document.getElementById("instance-text");
    if (s === null) {
      console.warn("cannot find instance text");
      return;
    }
    const a = s.textContent;
    if (!a || a === "") {
      console.log("text content in instance");
      return;
    }
    const h = new z(void 0, {
      splitOnRegEx: !1
    });
    o.map((u) => h.map(u, u));
    const c = a.split(" ");
    let l = !1, f = "", d = "";
    for (const u of c) {
      const p = f + u, g = h.search(p);
      if (g.length === 0 && l) {
        d += `
                <mark aria-hidden="true" class="emphasis">${f}</mark>
                `, d += u + " ", f = "", l = !1;
        continue;
      }
      if (g.length === 0) {
        d += u + " ", f = "";
        continue;
      }
      if (g.length === 1 && g[0] === p) {
        d += `
                <mark aria-hidden="true" class="emphasis">${p}</mark>
                `, f = "", l = !1;
        continue;
      }
      g.includes(p) && (l = !0), f = p + " ";
    }
    s.innerHTML = d;
  }
  function n(o) {
    console.log(o);
  }
  const e = t("emphasis");
  e !== void 0 && i(e);
  const r = t("suggestions");
  r !== void 0 && n(r);
})();
