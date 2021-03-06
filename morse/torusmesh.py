import matplotlib.pyplot as plt
import matplotlib.collections as mc
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
import heapq
from bitarray import bitarray
from collections import deque
import networkx as nx
import threading

import morse.unionfind
import copy
import re
import warnings


def _simplify_arc(arc):
    """
    Удалить возвратные пути (усы) из дуги.
    Пускаем два итератора с разных концов. Если значения совпадут
    :param arc:
    :return:
    """
    it = 0
    arc_num = len(arc)
    # Находим подпоследовательность ABA в дуге — конец уса.
    while it < arc_num - 2:
        if arc[it - 1] == arc[it + 1]:
            # idx — конец уса.
            mustache_len = 1  # Длина уса
            while arc[it - mustache_len - 1] == arc[it + mustache_len + 1]:
                mustache_len += 1
            del arc[it - mustache_len: it + mustache_len]  # Удаляем ус
            arc_num -= mustache_len * 2
            it -= mustache_len  # Перемещаем итератор
        else:
            it += 1


class TorusMesh:
    """
    Прямоугольная сетка на торе
    """

    def __init__(self, lx, ly):
        self.sizeX = lx  # Размеры сетки по X и Y
        self.sizeY = ly
        self.size = lx * ly  # Количество вершин
        self.values = np.zeros((self.sizeX, self.sizeY))  # Значения сетки
        self.cr_cells = []  # Список критических клеток
        self.V = [None] * (4 * self.size)  # Дискретный градиент
        self.cr_id = np.zeros(4 * self.size, dtype=bool)  # Индикатор критических клеток
        self.msgraph = nx.MultiGraph()  # Граф Морса-Смейла
        self.ppairs = []  # Список персистентных пар
        self.arcs = {}  # Дуги комплекса Морса-Смейла

    def set_values(self, val):
        """
        :param val: NumPy array
        """
        self.values = val

    def dim(self, idx):
        """
        Размерность клетки
        """
        if idx < self.size:
            return 0
        elif idx < 3 * self.size:
            return 1
        else:
            return 2

    def cp(self, morse_index):
        """
        Вывести критические точки с данным индексом Морса.
        :param morse_index: Индекс Морса критической точки
        :return: список индексов критических точек
        """
        return [p for p in self.cr_cells if self.dim(p) == morse_index]

    def _to_index(self, x, y):
        """
        Глобальный индекс вершины по координатам сетки.
        """
        return x * self.sizeY + y

    def _vleft(self, idx):
        """
        Левый сосед вершины с заданным индексом
        """
        return idx - idx % self.sizeX + (idx + self.sizeX - 1) % self.sizeX

    def _vright(self, idx):
        """
        Правый сосед вершины с заданным индексом
        """
        return idx - idx % self.sizeX + (idx + 1) % self.sizeX

    def _vtop(self, idx):
        """
        Верхний сосед вершины с заданным индексом
        """
        return (idx + self.size - self.sizeX) % self.size

    def _vbottom(self, idx):
        """
        Нижний сосед вершины с заданным индексом
        """
        return (idx + self.sizeX) % self.size

    def _eleft(self, idx):
        """
        Левое инцидентное ребро для вершины с данным индексом
        :return: глобальный индекс ребра
        """
        return self.size + self._vleft(idx)

    def _eright(self, idx):
        """
        Правое инцидентное ребро для вершины с данным индексом
        :return: глобальный индекс ребра
        """
        return self.size + idx

    def _etop(self, idx):
        """
        Верхнее инцидентное ребро для вершины с данным индексом
        :return: глобальный индекс ребра
        """
        return self.size * 2 + self._vtop(idx)

    def _ebottom(self, idx):
        """
        Нижнее инцидентное ребро для вершины с данным индексом
        :return: глобальный индекс ребра
        """
        return self.size * 2 + idx

    def _flefttop(self, idx):
        """
        Левая-верхняя инцидентная ячейка для вершины с данным индексом
        :return: глобальный индекс ячейки
        """
        return self.size * 3 + self._vtop(self._vleft(idx))

    def _fleftbottom(self, idx):
        """
        Левая-нижняя инцидентная ячейка для вершины с данным индексом
        :return: глобальный индекс ячейки
        """
        return self.size * 3 + self._vleft(idx)

    def _frighttop(self, idx):
        """
        Правая-верхняя инцидентная ячейка для вершины с данным индексом
        :return: глобальный индекс ячейки
        """
        return self.size * 3 + self._vtop(idx)

    def _frightbottom(self, idx):
        """
        Правая-нижняя инцидентная ячейка для вершины с данным индексом
        :return: глобальный индекс ячейки
        """
        return self.size * 3 + idx

    def _facets(self, idx):
        """
        @tested
        Гиперграни ячейки с данным индексом
        """
        if self.dim(idx) == 2:
            tmp_idx = idx - 3 * self.size  # индекс верхней левой вершины
            # верхнее, левое, нижнее, правое
            return self.size + tmp_idx, 2 * self.size + tmp_idx, self.size + self._vbottom(
                tmp_idx), 2 * self.size + self._vright(tmp_idx)
        else:
            return self._verts(idx)

    def _cofacets(self, idx):
        """
        @tested
        Пара инцидентных ребру IDX клеток
        :return: список из двух клеток
        """
        if self.dim(idx) != 1:
            raise AssertionError("Morse index must be 1!")
        if idx < 2 * self.size:  # горизонтальное ребро
            tmp_idx = idx - self.size
            return 3 * self.size + self._vtop(tmp_idx), 3 * self.size + tmp_idx
        else:  # вертикальное ребро
            tmp_idx = idx - 2 * self.size
            return 3 * self.size + self._vleft(tmp_idx), 3 * self.size + tmp_idx

    def _verts(self, idx):
        """
        @tested
        Множество вершин клетки
        """
        if idx < self.size:
            return idx,
        elif idx < 2 * self.size:
            return idx - self.size, self._vright(idx - self.size)
        elif idx < 3 * self.size:
            return idx - 2 * self.size, self._vbottom(idx - 2 * self.size)
        else:
            return idx - 3 * self.size, self._vright(idx - 3 * self.size), \
                   self._vbottom(self._vright(idx - 3 * self.size)), self._vbottom(idx - 3 * self.size)

    def _extvalue(self, idx):
        """
        Расширенное значение по глобальному индексу клетки.
        Значения в вершинах клетки по убыванию.
        """
        v = self._verts(idx)
        return tuple(sorted([self.value(v[i]) for i in range(len(v))], reverse=True))

    def coords(self, idx):
        """
        Координаты центра клетки (вершины, ребра или ячейки)
        X и Y меняем местами!
        """
        if idx < self.size:
            return self.coordy(idx), self.coordx(idx)
        elif idx < self.size * 2:
            return self.coordy(self._verts(idx)[0]), self.coordx(self._verts(idx)[0]) + 0.5
        elif idx < self.size * 3:
            return self.coordy(self._verts(idx)[0]) + 0.5, self.coordx(self._verts(idx)[0])
        else:
            return self.coordy(self._verts(idx)[0]) + 0.5, self.coordx(self._verts(idx)[0]) + 0.5

    def coordx(self, idx):
        """
        Координата X вершины
        """
        return idx % self.sizeX

    def coordy(self, idx):
        """
        Координата Y вершины
        """
        return idx // self.sizeX

    def value(self, idx):
        """
        Значение по глобальному индексу вершины.
        """
        return self.values[self.coordx(idx), self.coordy(idx)]

    def is_critical(self, idx):
        """
        Проверяем, является ли клетка с данным индексом критической.
        """
        return self.cr_id[idx]

    def set_critical(self, idx):
        """
        Указываем, что клетка является критической
        """
        self.cr_id[idx] = True
        self.cr_cells.append(idx)

    def unset_critical(self, idx):
        """
        Снять метку критической с клетки с данным индексом.
        :param idx: Индекс клетки
        :return:
        """
        self.cr_id[idx] = False
        self.cr_cells.remove(idx)

    def list_arcs(self):
        """
        Вывести список дуг
        :return:
        """
        return [item for sublist in self.arcs.values() for item in sublist]

    def find_arc(self, start_idx, end_idx, check_unique=True):
        """
        Поиск дуги с заданным началом и концом.
        :param check_unique: Проверка того, что дуга должна быть единственной.
        :param start_idx: Индекс клетки начала дуги.
        :param end_idx: Индекс клетки конца дуги.
        :return: Одна дуга. Если дуга не одна, то бросается исключение.
        """
        arcs_by_start_idx = self.arcs[start_idx]
        for arc in arcs_by_start_idx:
            if arc[-1] == end_idx:
                return arc
        raise RuntimeError("Дуга, соответствующая персистентной паре ({0}, {1}), не найдена!"
                           .format(start_idx, end_idx))

    def is_arc_inner(self, arc, x, y, lx, ly):
        """
        Проверяем, пересекает ли дуга границы заданного прямоугольника.
        Проверка тупая: смотрим, попали ли в прямоугольник её концы.
        :param arc: Дуга.
        :param x: вершины (нижней левой) прямоугольника
        :param y:
        :param lx:
        :param ly:
        :return:
        """
        return x <= self.coords(arc[0])[1] <= lx and y <= self.coords(arc[0])[0] <= ly and \
               x <= self.coords(arc[-1])[1] <= lx and y <= self.coords(arc[-1])[0] <= ly

    def is_arc_crossed_boundary(self, arc):
        """
        Проверка, пересекает ли дуга границу склейки.
        Проверяем, есть ли граничные клетки в дуге.
        :param arc:
        :return:
        """
        for cell in arc:
            for idx in self._verts(cell):
                if (idx < self.sizeX) or (idx % self.sizeY) == 0:
                    # print(cell)
                    return True
        return False

    def is_unpaired(self, idx):
        """
        Проверяем, является ли клетка спаренной или помеченной как критическая
        """
        return (self.V[idx] is None) and (not self.is_critical(idx))

    def unpaired_facets(self, idx, s):
        """
        Неспаренные гиперграни
        (в статье имеется в виду именно это, а не просто грани)
        данной 1- или 2-клетки,
        принадлежащих множеству s
        """
        facets = self._facets(idx)
        return [f for f in facets if f in s and self.is_unpaired(f)]

    def set_gradient_arrow(self, start, end):
        """
        Добавляем стрелку градиента
        """
        self.V[start] = end
        self.V[end] = start

    def get_min_neib_msgraph(self, cidx):
        """
        Соседи-минимумы седла в МС-графе.
        :return:
        """
        if self.dim(cidx) != 1:
            raise AssertionError("Функция get_min_neib_msgraph должна вызываться с аргументом-седлом")
        result = [edge[1] for edge in self.msgraph.edges(nbunch=cidx) if self.dim(edge[1]) == 0]
        if len(result) != 2:
            raise ValueError("Ошибка: у седла должны быть ровно два соседа-минимума!")
        return result

    def get_max_neib_msgraph(self, cidx):
        """
        Соседи-максимумы седла в МС-графе.
        Выводятся индексы в списке crit_cells.
        :return:
        """
        if self.dim(cidx) != 1:
            raise AssertionError("Функция get_min_neib_msgraph должна вызываться с аргументом-седлом")
        result = [edge[1] for edge in self.msgraph.edges(nbunch=cidx) if self.dim(edge[1]) == 2]
        if len(result) != 2:
            raise ValueError("Ошибка: у седла должны быть ровно два соседа-максимума!")
        return result

    def star(self, idx):
        """
        Звезда вершины idx
        :return: набор клеток звезды, содержащих данную вершину
        """
        return [self._eright(idx), self._etop(idx), self._eleft(idx), self._ebottom(idx),
                self._frighttop(idx), self._flefttop(idx), self._fleftbottom(idx), self._frightbottom(idx)]

    def lower_star(self, idx):
        """
        Вычисление нижней звезды вершины idx
        Список отсортирован по значению extval, т. е. первый элемент - ребро с наименьшим значением.
        :return:
        """
        v = self.value(idx)
        is_left_lower = self.value(self._vleft(idx)) < v
        is_top_lower = self.value(self._vtop(idx)) < v
        is_right_lower = self.value(self._vright(idx)) < v
        is_bottom_lower = self.value(self._vbottom(idx)) < v
        is_left_bottom_lower = self.value(self._vleft(self._vbottom(idx))) < v
        is_right_bottom_lower = self.value(self._vright(self._vbottom(idx))) < v
        is_left_top_lower = self.value(self._vleft(self._vtop(idx))) < v
        is_right_top_lower = self.value(self._vright(self._vtop(idx))) < v
        star = []
        if is_left_lower:
            star.append(self._eleft(idx))
        if is_top_lower:
            star.append(self._etop(idx))
        if is_right_lower:
            star.append(self._eright(idx))
        if is_bottom_lower:
            star.append(self._ebottom(idx))
        if is_left_lower and is_top_lower and is_left_top_lower:
            star.append(self._flefttop(idx))
        if is_right_lower and is_top_lower and is_right_top_lower:
            star.append(self._frighttop(idx))
        if is_left_lower and is_bottom_lower and is_left_bottom_lower:
            star.append(self._fleftbottom(idx))
        if is_right_lower and is_bottom_lower and is_right_bottom_lower:
            star.append(self._frightbottom(idx))
        star.sort(key=(lambda x: self._extvalue(x)))
        return star

    def cmp_discrete_gradient(self, log=True, threads_num=8):
        """
        Реализация процедуры вычисления дискретного градиента по исходным данным.
        Сюда включено вычисление критических клеток.
        ProcessLowerStars
        (Vanessa Robins)
        :param threads_num: Количество потоков для параллельного вычисления.
        :param log: Текстовый вывод.
        :return:
        """
        self.cr_cells = []
        self.V = [None] * (4 * self.size)
        self.cr_id = np.zeros(4 * self.size, dtype=bool)

        if log:
            print('Computation of discrete gradient field...', end='')

        def _process_star(idx):
            # Two additional heaps
            pq_zero = []
            pq_one = []

            lstar = self.lower_star(idx)
            if not lstar:
                self.set_critical(idx)  # Если значение в вершине меньше, чем во всех соседних, то она - минимум.
            else:
                delta = lstar[0]  # Ребро с наименьшим значением
                self.set_gradient_arrow(idx, delta)
                for i in range(1, len(lstar)):
                    if self.dim(lstar[i]) == 1:  # Остальные 1-клетки кладём в pq_zero
                        # Первое значение - ключ для сортировки кучи
                        heapq.heappush(pq_zero, (self._extvalue(lstar[i]), lstar[i]))
                # Ко-грани ребра delta
                cf = self._cofacets(delta)
                for f in cf:
                    if (f in lstar) and (len(self.unpaired_facets(f, lstar)) == 1):
                        heapq.heappush(pq_one, (self._extvalue(f), f))
                while pq_one or pq_zero:
                    while pq_one:
                        alpha = heapq.heappop(pq_one)
                        unpair_facets = self.unpaired_facets(alpha[1], lstar)
                        if not unpair_facets:
                            heapq.heappush(pq_zero, alpha)
                        else:
                            pair = unpair_facets[0]
                            self.set_gradient_arrow(pair, alpha[1])
                            # TODO: remove pair from pq_zero faster
                            pq_zero = [x for x in pq_zero if x[1] != pair]
                            # pq_zero.remove((self.extvalue(pair), pair))
                            heapq.heapify(pq_zero)
                            for beta in lstar:
                                if len(self.unpaired_facets(beta, lstar)) == 1 and ((alpha in self._facets(beta)) or (pair in self._facets(beta))):
                                    heapq.heappush(pq_one, (self._extvalue(beta), beta))
                    if pq_zero:
                        gamma = heapq.heappop(pq_zero)
                        self.set_critical(gamma[1])
                        for a in lstar:
                            if (gamma[1] in self._facets(a)) and (len(self.unpaired_facets(a, lstar)) == 1):
                                heapq.heappush(pq_one, (self._extvalue(a), a))

        def _process_stars_parallel(cell_list):
            for cell in cell_list:
                _process_star(cell)

        cell_num_in_thread = self.size // threads_num
        cell_blocks = [[cell_num_in_thread * i, cell_num_in_thread * (i + 1)] for i in range(threads_num)]
        cell_blocks[-1][1] = self.size
        threads = []

        print(cell_blocks)

        for i in range(threads_num):
            my_thread = threading.Thread(target=_process_stars_parallel,
                                         args=(list(range(cell_blocks[i][0], cell_blocks[i][1])),))
            threads.append(my_thread)

        for thr in threads:
            thr.start()

        # Method should finish after all threads are finished.
        for thr in threads:
            thr.join()

        # Сортируем клетки по возрастанию значения — получаем фильтрацию.
        self.cr_cells.sort(key=lambda idx: self._extvalue(idx))

        if log:
            print(" Completed.")

    def cmp_crit_cells(self):
        """
        Вычисление критических клеток по градиенту.
        ! Функция cmp_discrete_gradient вычисляет критические клетки по данным.
        ! Здесь критические точки вычисляются не по данным, а по градиенту.
        Если клетка не включена ни в одну стрелку градиента, то она критическая.
        Проверка на корректность градиента не производится.
        :return:
        """
        self.cr_cells = []
        self.cr_id = np.ones(4 * self.size, dtype=bool)
        for i in range(4 * self.size):
            if self.V[i] is not None:
                self.cr_id[i] = False
        self.cr_cells = [idx for idx in range(4 * self.size) if self.cr_id[idx]]

        # Сортируем клетки по возрастанию значения — получаем фильтрацию.
        self.cr_cells.sort(key=lambda idx: self._extvalue(idx))
        print("Осталось {0} критических точек".format(len(self.cr_cells)))

    def cmp_msgraph(self):
        """
        Вытаскиваем информацию о соседстве в MS-комплексе.
        На выходе - список, каждой критической клетке сопоставляется список её соседей в MS-графе.
        """
        self.msgraph = nx.MultiGraph()
        self.msgraph.add_nodes_from(self.cr_cells)

        morse_index = dict()

        for index in [0, 1, 2]:
            for p in self.cp(index):
                morse_index[p] = index

        # Устанавливаем координаты критических точек и индекс Морса в качестве атрибутов.
        nx.set_node_attributes(self.msgraph, dict(list(map(lambda p: (p, self.coords(p)[0]), self.cr_cells))), "x")
        nx.set_node_attributes(self.msgraph, dict(list(map(lambda p: (p, self.coords(p)[1]), self.cr_cells))), "y")
        nx.set_node_attributes(self.msgraph, morse_index, "morse_index")

        q = deque()

        for dimension in (1, 2):
            for cidx in self.cp(dimension):
                g = self._facets(cidx)
                for face in g:
                    if self.is_critical(face):
                        self.msgraph.add_edge(cidx, face)
                    elif self.V[face] > face:  # То есть есть стрелка, и она выходит (а не входит)
                        q.appendleft(face)
                while q:
                    a = q.pop()
                    b = self.V[a]
                    for face in self._facets(b):
                        if face == a:
                            continue  # Возвращаться нельзя
                        if self.is_critical(face):
                            self.msgraph.add_edge(cidx, face)
                        elif self.V[face] > face:
                            q.appendleft(face)

    def _cmp_arcs(self, s):
        """
        Вычислить все дуги, следующие из некоторого седла.
        :param s: Индекс седла.
        :return:
        """
        self.arcs[s].clear()

        # Вычисляем сепаратрисы седло-минимум
        vertices = self._verts(s)

        for cur_v in vertices:
            # Идём в двух возможных направлениях
            cur_e = s
            separx = [cur_e, cur_v]  # Новая сепаратриса
            # Идём по сепаратрисе, пока не встретим критическую клетку

            while not self.is_critical(cur_v):
                # Идём вдоль интегральной линии
                cur_e = self.V[cur_v]
                v = self._verts(cur_e)
                # Выбираем путь вперёд (в ещё не пройденную клетку)
                cur_v = v[1] if v[0] == cur_v else v[0]
                separx.append(cur_e)
                separx.append(cur_v)
            self.arcs[s].append(separx)

        # Вычисляем сепаратрисы седло-максимум
        faces = self._cofacets(s)

        # Идём в двух возможных направлениях
        for cur_f in faces:
            cur_e = s
            separx = [cur_e, cur_f] # Новая сепаратриса
            while not self.is_critical(cur_f):
                # Идём вдоль интегральной линии
                cur_e = self.V[cur_f]
                f = self._cofacets(cur_e)
                # Выбираем путь вперёд (в ещё не пройденную клетку)
                cur_f = f[1] if f[0] == cur_f else f[0]
                separx.append(cur_e)
                separx.append(cur_f)
            self.arcs[s].append(separx)

    def cmp_arcs(self):
        """
        Вычисляем сепаратрисы MS-комплекса.
        :return:
        """
        self.arcs = dict([(saddle, []) for saddle in self.cp(1)])  # В качестве ключей — индексы сёдел.
        for s in self.arcs.keys(): # Цикл по сёдлам
            self._cmp_arcs(s)

    def cmp_persistent_pairs(self, log=False):
        """
        Вычисление персистентных пар.
        :return:
        """
        critical_cells_num = len(self.cr_cells) # Количество критических клеток

        if log:
            print('{0} critical points'.format(critical_cells_num))

        # Помечаем критические клетки как негативные (создающие цикл) или позитивные (убивающие цикл).
        # Метки критических клеток (негативная / позитивная)
        signs = bitarray(critical_cells_num)

        # Строим отображение критических точек в индекс битового массива меток
        idx_reverse = {self.cr_cells[cidx]: cidx for cidx in range(len(self.cr_cells))}

        uf = morse.unionfind.UnionFind(critical_cells_num)

        # Cчитаем, что к этому моменту массив критических точек представляет собой фильтрацию.
        for i in range(len(self.cr_cells)):
            cidx = self.cr_cells[i]
            dim = self.dim(cidx)  # размерность критической клетки
            uf.makeset(i)
            if dim == 0:
                signs[i] = 1 # все минимумы - позитивные
            elif dim == 1:
                # находим двух соседей в ms-комплексе, которые являются минимумами
                # у каждого седла два соседа-минимума и два соседа-максимума
                neighbours = self.get_min_neib_msgraph(cidx)  # соседи-минимумы в графе ms-комплекса
                if uf.find(idx_reverse[neighbours[0]]) == uf.find(idx_reverse[neighbours[1]]):
                    signs[i] = 1  # седло порождает 1-цикл
                else:
                    signs[i] = 0  # седло убивает 0-цикл
                uf.union(idx_reverse[neighbours[0]], idx_reverse[neighbours[1]])  # Объединяем компоненты связности
            else:
                signs[i] = 0  # все максимумы - негативные

        # Собственно, вычисление персистентных пар.
        # Несортированный массив персистентных пар
        pairs = []

        # список циклов
        # каждый цикл соответствует негативной клетке
        cycles = [None] * critical_cells_num

        curset = critical_cells_num * bitarray('0')

        # Персистентность пары
        def persistence(cidx1, cidx2):
            return np.abs(np.max(self._extvalue(cidx1)) - np.max(self._extvalue(cidx2)))

        # проходим по прямой фильтрации
        for i in range(critical_cells_num):
            if log:
                print('.', end='')
            cidx = self.cr_cells[i]
            # Смотрим только негативные сёдла
            if self.dim(cidx) == 1 and not signs[i]:
                for neighbor in self.get_min_neib_msgraph(cidx):
                    curset[idx_reverse[neighbor]] = True   # 5:
                while curset.count() > 0:
                    # Последнее вхождение единицы в битовый массив (если её нет — ValueError)
                    s = curset.to01().rindex('1')  # 9:
                    if not cycles[s]:
                        cycles[s] = copy.deepcopy(curset)
                        cycles[i] = copy.deepcopy(curset)
                        pairs.append((self.cr_cells[i], self.cr_cells[s], persistence(self.cr_cells[i], self.cr_cells[s])))
                    else:
                        for b in re.finditer('1', cycles[s].to01()):  # 16:
                            idx = b.span()[0]
                            curset[idx] ^= 1  # bit flip operation

        curset = len(self.cr_cells) * bitarray('0')

        # проходим по обратной фильтрации
        for i in reversed(range(critical_cells_num)):
            if log:
                print('.', end='')
            cidx = self.cr_cells[i]
            # Смотрим только позитивные сёдла
            if self.dim(cidx) == 1 and signs[i]:
                for neighbor in self.get_max_neib_msgraph(cidx):
                    curset[idx_reverse[neighbor]] = True
                while curset.count() > 0:
                    # Первое вхождение единицы в битовый массив (если её нет — ValueError)
                    s = curset.to01().index('1')
                    if not cycles[s]:
                        cycles[s] = copy.deepcopy(curset)
                        cycles[i] = copy.deepcopy(curset)
                        pairs.append((self.cr_cells[i], self.cr_cells[s], persistence(self.cr_cells[i], self.cr_cells[s])))
                    else:
                        for b in re.finditer('1', cycles[s].to01()):  # 16:
                            idx = b.span()[0]
                            curset[idx] ^= 1  # bit flip operation

        pairs.sort(key=lambda x: x[2], reverse=True)  # Сортируем пары по убыванию значения
        self.ppairs = pairs

    def eliminate_pair_revert_gradient(self, log=False):
        """
        Сократить следующую по очерёдности персистентную пару.
        !При помощи разворота градиента!
        На сокращаемой дуге разворачивается градиент, затем удаляются дуги, следующие из удалённого седла;
        производится локальный пересчёт дуг по новому градиенту.
        Вручную исправляются записи в МС-графе, удаляются критические точки из пары.
        :param log: Включить текстовый вывод.
        :return:
        """
        # Если пар не осталось, то сокращать нечего.
        if not self.ppairs:
            print("Список персистентных пар пуст!")
            return
        # Первая клетка — седло, вторая — максимум или минимум.
        pair = self.ppairs.pop()
        saddle = pair[0]
        if self.dim(saddle) != 1:
            raise AssertionError("Первая клетка пары должна быть седлом!")
        extr = pair[1]
        extr_dim = self.dim(extr)

        # Сёдла-соседи экстремума (кроме седла из пары)
        saddles = [edge[1] for edge in self.msgraph.edges(nbunch=extr) if edge[1] != saddle]

        # Минимумы (максимумы) - соседи седла
        mins_or_maxs = self.get_min_neib_msgraph(saddle) if extr_dim == 0 else self.get_max_neib_msgraph(saddle)
        # Вторая клетка-минимум (максимум)
        min_or_max = mins_or_maxs[0] if mins_or_maxs[0] != extr else mins_or_maxs[1]
        # Разворот градиента.
        if extr_dim == 1:
            raise AssertionError("Вторая клетка пары должна быть максимумом или минимумом!")
        arc = self.find_arc(saddle, extr, check_unique=True)
        # Разворачиваем градиент вдоль дуги.
        for i in range(0, len(arc), 2):
            self.set_gradient_arrow(arc[i], arc[i + 1])
        # Удаляем критические точки
        self.unset_critical(saddle)
        self.unset_critical(extr)
        # Удаляем дуги из удалённого седла
        self.msgraph.remove_node(saddle)
        del self.arcs[saddle]
        # Пересчитываем дуги из сёдел (согласно дискретному градиенту)
        for s in saddles:
            self.msgraph.remove_edge(s, extr)
            self.msgraph.add_edge(s, min_or_max)
            self._cmp_arcs(s)
        if log:
            print("Pair {0} eliminated.".format(pair))

        self.msgraph.remove_node(extr)

    def eliminate_pair_change_msgraph(self, log=False):
        """
        Сократить следующую по очерёдности персистентную пару.
        !Изменяется граф Морса-Смейла!
        Берётся следущая по очереди персистентная пара.
        Критические точки из пары удаляются, новые дуги получаются продолжением через дугу, обратную сокращённой.
        (см. Sousbie)
        :param log: Текстовый вывод.
        :return:
        """
        # Если пар не осталось, то сокращать нечего.
        if not self.ppairs:
            print("Список персистентных пар пуст!")
            return
        # Первая клетка — седло, вторая — максимум или минимум.
        pair = self.ppairs.pop()
        saddle = pair[0]
        if self.dim(saddle) != 1:
            raise AssertionError("Первая клетка пары должна быть седлом!")
        extr = pair[1]
        extr_dim = self.dim(extr)

        if extr_dim == 1:
            raise AssertionError("Вторая клетка пары должна быть максимумом или минимумом!")

        # Изменение графа Морса-Смейла.
        #  Сёдла-соседи максимума (кроме седла из пары)
        saddles = [edge[1] for edge in self.msgraph.edges(nbunch=extr) if edge[1] != saddle]

        # Минимумы (максимумы) - соседи седла
        mins_or_maxs = self.get_min_neib_msgraph(saddle) if extr_dim == 0 else self.get_max_neib_msgraph(saddle)
        # Вторая клетка-минимум (максимум)
        min_or_max = mins_or_maxs[0] if mins_or_maxs[0] != extr else mins_or_maxs[1]

        self.msgraph.remove_node(saddle)
        for s in saddles:
            # Добавляем рёбра из соседей минимума (максимума) в другой минимум (максимум)
            self.msgraph.remove_edge(s, extr)
            self.msgraph.add_edge(s, min_or_max)

        self.msgraph.remove_node(extr)

        # Дуга, продолжающая дуги из сёдел-соседей экстремума
        arc_extension = list(reversed(self.find_arc(saddle, extr, check_unique=True)[1: -1]))
        arc_extension.extend(self.find_arc(saddle, min_or_max, check_unique=True))
        # Проводим новые дуги
        for s in saddles:
            arc = self.find_arc(s, extr, check_unique=True)
            arc.extend(arc_extension)
            # Удаляем усы
            _simplify_arc(arc)
        # Удаляем дуги из седла
        del self.arcs[saddle]
        # Удаляем критические точки
        self.unset_critical(saddle)
        self.unset_critical(extr)
        if log:
            print("Pair {0} eliminated".format(pair))

    def simplify_by_level(self, level, method='gradient', log=True):
        """
        Упрощение до заданного уровня.
        :param method: Метод, которым сокращаются персистентные пары.
            'gradient' — методом обращения градиента
            'arc' — методом восстановления дуг
        :param level: Уровень, до которого сокращаем персистентные пары.
        :param log: Текстовый вывод.
        :return:
        """
        possible_methods = ('gradient', 'arc')
        if method not in possible_methods:
            raise AssertionError("Аргумент 'method' указан неверно. Допустимые значения: {0}".format(possible_methods))

        pairs_elimination_num = len([pair for pair in self.ppairs if pair[2] < level])
        checkpoints_num = 20
        current_checkpoint = 0

        if log:
            print('Simplification...', end='')

        for i in range(pairs_elimination_num):
            if log and i > pairs_elimination_num * current_checkpoint / checkpoints_num:
                current_checkpoint += 1
                print('.', end='')

            if method == 'gradient':
                self.eliminate_pair_revert_gradient()
            elif method == 'arc':
                self.eliminate_pair_change_msgraph()

        # Упрощаем дуги (удаляем усы)
        # if method == 'arc':
        #     for arc in self.arcs:
        #         _simplify_arc(arc)

        if log:
            print('\nSimplification completed. {0} pairs eliminated.'.format(pairs_elimination_num))

    def simplify_by_percent(self, percentage, method='gradient', log=True):
        """
        Упрощение заданного процента персистентных пар.
        :param method: Метод, которым сокращаются персистентные пары.
            'gradient' — методом обращения градиента
            'arc' — методом восстановления дуг
        :param percentage: Процент персистентных пар для упрощения. Значение от 0 до 100.
        :param log: Текстовый вывод.
        :return:
        """
        possible_methods = ('gradient', 'arc')
        if method not in possible_methods:
            raise AssertionError("Аргумент 'method' указан неверно. Допустимые значения: {0}".format(possible_methods))
        if percentage > 100 or percentage < 0:
            raise AssertionError("Процент должен лежать в интервале от 0 до 100!")

        pairs_elimination_num = int(percentage * 0.01 * len(self.ppairs))
        checkpoints_num = 20
        current_checkpoint = 0

        if log:
            print('Simplification...', end='')

        for i in range(pairs_elimination_num):
            if log and i > pairs_elimination_num * current_checkpoint / checkpoints_num:
                current_checkpoint += 1
                print('.', end='')
            if method == 'gradient':
                self.eliminate_pair_revert_gradient()
            elif method == 'arc':
                self.eliminate_pair_change_msgraph()

        if log:
            print('\nSimplification completed. {0} pairs eliminated.'.format(pairs_elimination_num))

    def simplify_by_pairs_remained(self, pairs_remained, method='gradient', log=True):
        """
        Упрощаем до заданного оставшегося количества персистентных пар.
        :param pairs_remained:
        :param method:
        :param log:
        :return:
        """
        possible_methods = ('gradient', 'arc')
        if method not in possible_methods:
            raise AssertionError("Аргумент 'method' указан неверно. Допустимые значения: {0}".format(possible_methods))
        if pairs_remained > len(self.ppairs):
            warnings.warn("Текущее количество пар меньше указанного! Пары не будут сокращены")
            return
        if pairs_remained < 2:
            raise AssertionError("Нужно оставить хотя бы 2 пары.")

        pairs_elimination_num = len(self.ppairs) - pairs_remained
        checkpoints_num = 20
        current_checkpoint = 0

        if log:
            print('Simplification...', end='')

        for i in range(pairs_elimination_num):
            if log and i > pairs_elimination_num * current_checkpoint / checkpoints_num:
                current_checkpoint += 1
                print('.', end='')
            if method == 'gradient':
                self.eliminate_pair_revert_gradient()
            elif method == 'arc':
                self.eliminate_pair_change_msgraph()

        if log:
            print('\nSimplification completed. {0} pairs eliminated.'.format(pairs_elimination_num))

    def plot_persistence_diagram(self, betti=None):
        """
        Вывести диаграмму персистентности.
        :param plot:
        :param betti: диаграмма для заданного индекса.
            Если 0 - для компонент связности, 1 - для циклов, None - для всего сразу.
        :return:
        """
        # !! ~SIC: Max, поскольку значение в минимуме определяется однозначно,
        # а в максимуме размазано по 4 клеткам.
        birth_times = list(map(lambda pair: np.max(self._extvalue(pair[0])), self.ppairs))
        death_times = list(map(lambda pair: np.max(self._extvalue(pair[1])), self.ppairs))
        if betti == 0:
            idx = [_ for _ in range(len(birth_times)) if birth_times[_] > death_times[_]]
            birth_times, death_times = [death_times[i] for i in idx], [birth_times[i] for i in idx]
        elif betti == 1:
            idx = [_ for _ in range(len(birth_times)) if birth_times[_] < death_times[_]]
            birth_times, death_times = [birth_times[i] for i in idx], [death_times[i] for i in idx]
        elif betti is None:
            birth_times, death_times = [min(birth_times[i], death_times[i]) for i in range(len(birth_times))],\
                                       [max(birth_times[i], death_times[i]) for i in range(len(death_times))]
        plt.scatter(birth_times, death_times, c='k', s=4)
        plt.plot([0, max(death_times)], [0, max(death_times)], '--k')
        plt.xlim(0, max(death_times))
        plt.ylim(0, max(death_times))
        return birth_times, death_times

    def get_critical_points(self, morse_index):
        """
        Get coordinates of critical points by Morse index.
        :param morse_index: Morse index of critical points.
        :return: tuple (X, Y) of X and Y point coordinates.
        """
        points_idx = self.cp(morse_index)
        return [self.coords(p)[0] for p in points_idx], [self.coords(p)[1] for p in points_idx]

    def get_arcs(self, cut=None):
        """
        Get coordinates of arcs of MS-complex.
        :param cut: Cut arcs passing through border of rectangle; pass here rectangle cut=(x0, y0, x1, y1).
        :return: tuple (X, Y) of X and Y point coordinates.
        """
        arcs = []
        for arc in self.list_arcs():
            new_arc = []
            if (cut is None) or self.is_arc_inner(arc, *cut):  # Отбрасываем граничные дуги
                for idx in range(len(arc) - 1):
                    edge = [self.coords(arc[idx]), self.coords(arc[idx + 1])]
                    if np.abs(edge[0][0] - edge[1][0]) < 1 and np.abs(edge[0][1] - edge[1][1]) < 1:
                        new_arc.append(edge[0])
                    else:
                        if len(new_arc) > 1:
                            arcs.append(new_arc)
                        new_arc = []
                if len(new_arc) > 1:
                    arcs.append(new_arc)
        return arcs

    def print(self):
        print(self.values)

    def draw_3d(self):
        fig = plt.figure()
        x, y = np.meshgrid(range(self.sizeY), range(self.sizeX))
        ax = fig.gca(projection='3d')
        ax.plot_surface(x, y, self.values, cmap=cm.gray, linewidth=0, antialiased=True)

    def draw(self,
             draw_crit_pts=True, annotate_crit_points=False, annotate_values=False,
             draw_persistence_pairs=False, draw_gradient=False, draw_arcs=True,
             draw_graph=False, draw_image=True, fname=None, cut=None,
             cmap='gray', max_color=(1, 0, 0), min_color=(0, 0, 1), saddle_color=(0, 1, 0),
             vmin=None, vmax=None):
        """
        Draw mesh values.
        :param saddle_color: Color of saddle points.
        :param max_color: Color of maxima points.
        :param min_color: Color of minima points.
        :param cmap:
            Color map for image drawing.
        :param annotate_values:
            Annotate values at each point (use only with small fields).
        :param draw_crit_pts:
            Show critical points positions and types.
        :param annotate_crit_points:
            Annotate number of critical points in self.cr_cells.
        :param draw_persistence_pairs:
            Draw lines connecting persistence pairs of critical points.
        :param draw_gradient:
            Draw gradient arrows.
        :param draw_arcs:
            Draw arcs of MS-complex.
        :param draw_graph:
            Draw MS-graph.
        :param draw_image:
            Draw field on the background.
        :param fname:
            Save image to the PNG-file.
        :param cut:
            Tuple (minX, minY, maxX, maxY).
            Cut part of image.
        :param vmin:
            Minimal value to draw (for colormap).
            By default, choose automatically.
        :param vmax:
            Maximal value to draw (for colormap).
            By default, choose automatically.
        """
        plt.figure()
        if cut is None:
            plt.gca().set_xlim(0, self.sizeY)
            plt.gca().set_ylim(0, self.sizeX)
        else:
            plt.gca().set_xlim(cut[1], cut[3])
            plt.gca().set_ylim(cut[0], cut[2])

        figManager = plt.get_current_fig_manager()
        figManager.window.showMaximized()
        if draw_image:
            cur_plot = plt.imshow(self.values, cmap=cmap, vmin=vmin, vmax=vmax)
            plt.colorbar(cur_plot)
        if draw_graph:
            edges = []
            for cidx in self.cr_cells:
                for cidx2 in self.msgraph[cidx]:
                    edges.append([self.coords(cidx), self.coords(cidx2)])
            lc = mc.LineCollection(edges, colors='k', linewidths=2, zorder=1)
            plt.gca().add_collection(lc)
        if draw_gradient:
            x, y, X, Y = [], [], [], []
            for idx in range(len(self.V)):
                if self.V[idx] is None:
                    continue
                if idx < self.V[idx]:
                    start = self.coords(idx)
                    end = self.coords(self.V[idx])
                    if start[0] != 0 and end[0] != 0 and start[1] != 0 and end[1] != 0:
                        x.append(start[0])
                        y.append(start[1])
                        X.append(end[0] - start[0])
                        Y.append(end[1] - start[1])
            plt.quiver(x, y, X, Y, scale_units='x', angles='xy', scale=2)
        if draw_arcs:
            edges = []
            for arc in self.list_arcs():
                if (cut is None) or self.is_arc_inner(arc, *cut):  # Отбрасываем граничные дуги
                    for idx in range(len(arc) - 1):
                        edge = [self.coords(arc[idx]), self.coords(arc[idx + 1])]
                        if np.abs(edge[0][0] - edge[1][0]) < 1 and np.abs(edge[0][1] - edge[1][1]) < 1:
                            edges.append([self.coords(arc[idx]), self.coords(arc[idx + 1])])
            lc = mc.LineCollection(edges, colors='k', linewidths=1, zorder=1)
            plt.gca().add_collection(lc)
        if draw_crit_pts:
            plt.scatter([self.coords(p)[0] for p in self.cp(0)],
                        [self.coords(p)[1] for p in self.cp(0)], zorder=2, c=min_color, edgecolors='k', s=50)
            plt.scatter([self.coords(p)[0] for p in self.cp(1)],
                        [self.coords(p)[1] for p in self.cp(1)], zorder=2, c=saddle_color, edgecolors='k', s=50)
            plt.scatter([self.coords(p)[0] for p in self.cp(2)],
                        [self.coords(p)[1] for p in self.cp(2)], zorder=2, c=max_color, edgecolors='k', s=50)
        if annotate_crit_points:
            for cidx in self.cr_cells:
                plt.text(self.coords(cidx)[0], self.coords(cidx)[1], str(cidx))
        if annotate_values:
            for idx in range(self.size):
                plt.text(self.coords(idx)[0], self.coords(idx)[1], '{:.2f}'.format(self.value(idx)))
        if draw_persistence_pairs:
            edges = []
            for pairs in self.ppairs:
                edges.append([self.coords(pairs[0]), self.coords(pairs[1])])
            lc = mc.LineCollection(edges, colors='r', linewidths=2, zorder=1)
            plt.gca().add_collection(lc)
        if fname:
            plt.savefig(fname)
            plt.close()

    def get_cut_morse_graph(self):
        """
        Граф Морса с удалёнными рёбрами, проходящими через границу склейки в тор.
        :return:
        """
        g = nx.Graph(self.msgraph)

        # TODO: учесть дублирующиеся дуги.
        for arc in self.list_arcs():
            if self.is_arc_crossed_boundary(arc):
                try:
                    g.remove_edge(arc[0], arc[-1])
                except nx.exception.NetworkXError:
                    pass
                    # print('edge {0}->{1} is already removed'.format(arc[0], arc[-1]))
        return g

    @classmethod
    def build_all(cls, field, threads_num=8, log=False):
        """
        Построить комплекс Морса-Смейла одной функцией.
        :param threads_num: Количество потоков.
        :param log:
        :param field:
        :return:
        """
        mesh = TorusMesh(*field.shape)
        mesh.set_values(field)
        mesh.cmp_discrete_gradient(threads_num=threads_num, log=log)
        mesh.cmp_msgraph()
        mesh.cmp_arcs()
        mesh.cmp_persistent_pairs(log=log)
        return mesh


def test():
    """
    Максимум 27
    два минимума 2, 7
    три седла 15, 16, 23
    """
    field = np.asarray([[2, 8, 1, 10], [9, 5, 6, 11], [7, 3, 4, 12]])
    m = TorusMesh(3, 4)
    m.set_values(field)
    m.cmp_discrete_gradient()
    m.cmp_msgraph()
    m.cmp_arcs()
    m.cmp_persistent_pairs()
    # m.simplify_by_level(100, method='gradient')
    m.draw(draw_gradient=False, draw_arcs=True, draw_graph=False, draw_persistence_pairs=True, annotate_values=True)
    plt.show()


def test2():
    import matplotlib
    matplotlib.use('Qt5Agg')
    import morse.field_generator
    import time
    data = morse.field_generator.gen_field_from_file(r"C:/repo/pproc/data/input.fits",
                                                     filetype='fits', conditions='plain')
    start_time = time.time()
    # data = data[100:300, 100:300]
    m = TorusMesh.build_all(field=data, threads_num=4)
    print('Mesh computed in {0}'.format(time.time() - start_time))
    m.simplify_by_pairs_remained(20)
    print(m.get_critical_points(0))
    m.draw()


def test3():
    import morse.field_generator
    data = morse.field_generator.gen_gaussian_sum_rectangle(50, 50,
                [(10, 10), (15, 15), (10, 15), (20, 5)], 5)
    data = morse.field_generator.perturb(data)
    m = TorusMesh.build_all(data)
    m.simplify_by_pairs_remained(20, method='arc')
    m.draw()

    # positions = dict(list(zip(nx.nodes(m.msgraph), list(zip(nx.get_node_attributes(m.msgraph, "x").values(),
    #                                                         nx.get_node_attributes(m.msgraph, "y").values())))))
    # colors = ['b', 'g', 'r']
    # color_map = list(map(lambda v: colors[v], nx.get_node_attributes(m.msgraph, "morse_index").values()))
    #
    # nx.draw(m.msgraph, pos=positions, node_color=color_map, node_size=30)
    # plt.show()
    #
    # print(m.arcs)
    #
    # nx.draw(m.get_cut_morse_graph(), pos=positions, node_color=color_map, node_size=30)
    # plt.show()

